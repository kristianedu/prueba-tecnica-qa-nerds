"""
Diagnóstico de errores del proveedor.

Cuando una corrida de 71 llamadas se cae a mitad, el mensaje de error es lo
único que tiene delante quien la lanzó. Si ese mensaje apunta a la causa
equivocada, se pierde más tiempo persiguiendo el problema falso que el que
costó el fallo.

Estas pruebas nacen de un caso real: Groq agotó la cuota diaria de tokens y el
runner respondió "Si el modelo ya no existe, consulta los disponibles con...".
El heurístico buscaba la palabra "model" en el texto, y el mensaje de un límite
de cuota también la contiene.
"""

from __future__ import annotations

import pytest

from llm_client import _diagnostico, segundos_de_espera

CUOTA_DIARIA = (
    "Error code: 429 - Rate limit reached for model `openai/gpt-oss-120b` in "
    "organization `org_x` service tier `on_demand` on tokens per day (TPD): "
    "Limit 200000, Used 199236, Requested 1682. Please try again in 6m36.576s"
)


@pytest.mark.parametrize("mensaje,esperado", [
    ("Please try again in 6m36.576s", 396.576),
    ("Please try again in 8.5s", 8.5),
    ("Please try again in 2m0s", 120.0),
    ("algo falló sin indicar cuándo reintentar", None),
])
def test_extrae_la_espera_pedida(mensaje, esperado):
    assert segundos_de_espera(Exception(mensaje)) == esperado


def test_la_cuota_diaria_no_se_confunde_con_un_modelo_inexistente():
    """La regresión: el mensaje contiene 'model', pero el problema es la cuota."""
    d = _diagnostico(Exception(CUOTA_DIARIA), "groq", "openai/gpt-oss-120b")

    assert "Cuota DIARIA" in d
    assert "199236 de 200000" in d
    assert "--listar-modelos" not in d       # esa pista sería engañosa aquí


def test_la_cuota_diaria_sugiere_salidas_concretas():
    d = _diagnostico(Exception(CUOTA_DIARIA), "groq", "openai/gpt-oss-120b")
    assert "--modelo-juez" in d              # usar otro juez
    assert "--sin-cache" in d                # o reutilizar lo ya guardado


def test_modelo_inexistente_sugiere_listar_modelos():
    d = _diagnostico(Exception("model_not_found: the model does not exist"), "groq", "viejo")
    assert "--listar-modelos" in d
    assert "Cuota" not in d


def test_credencial_invalida_apunta_al_env():
    d = _diagnostico(Exception("401 Unauthorized: Invalid API Key"), "groq", "x")
    assert "GROQ_API_KEY" in d


def test_un_error_desconocido_no_inventa_diagnostico():
    """
    Ante algo que no se reconoce, mejor no decir nada que mandar en la dirección
    equivocada: el mensaje original del proveedor se muestra igual.
    """
    assert _diagnostico(Exception("connection reset by peer"), "groq", "x") == ""


# ------------------------------------- los dos tipos de límite se tratan al revés

def test_el_limite_por_minuto_pide_una_espera_corta():
    """
    Regresión de un error propio: al arreglar los reintentos inútiles contra la
    cuota diaria, se rompió el caso del límite por minuto, donde esperar los
    segundos que pide el proveedor SÍ resuelve. Una corrida de 30 turnos roza
    ese límite constantemente, porque el juez consume miles de tokens por turno.
    """
    from llm_client import ESPERA_MAXIMA_S
    espera = segundos_de_espera(Exception(
        "429 Rate limit reached on tokens per minute (TPM). Please try again in 7.2s"
    ))
    assert espera is not None and espera <= ESPERA_MAXIMA_S   # se espera y se reintenta


def test_la_cuota_diaria_pide_una_espera_larga():
    from llm_client import ESPERA_MAXIMA_S
    espera = segundos_de_espera(Exception(CUOTA_DIARIA))
    assert espera is not None and espera > ESPERA_MAXIMA_S    # se corta de inmediato


TOPE_SALIDA = (
    "Error code: 429 - Request too large for model `qwen/qwen3.8-27b` in organization "
    "`org_x` service tier `on_demand` on output tokens per minute (OTPM): Limit 1000, "
    "Requested 1329. The request's expected output tokens exceed the enforced limit; "
    "reduce max_tokens (or the request's expected output) and try again."
)


def test_el_tope_de_salida_por_peticion_sugiere_bajar_max_tokens():
    """
    Tercer tipo de 429, distinto de los otros dos: no hay espera que valga porque
    la petición se rechaza de entrada por el max_tokens declarado. El remedio es
    pedir menos, y el diagnóstico tiene que decirlo con la bandera exacta.
    """
    d = _diagnostico(Exception(TOPE_SALIDA), "groq", "qwen/qwen3.8-27b")
    assert "--max-tokens-juez" in d
    assert "límite 1000, pedidos 1329" in d
    assert "Cuota DIARIA" not in d
    assert segundos_de_espera(Exception(TOPE_SALIDA)) is None   # no pide esperar


# ------------------------------------------------ códigos de salida del runner

def test_los_codigos_de_salida_no_pisan_el_del_crash():
    """
    Pasó en CI: el runner se cayó por cuota (excepción sin capturar → código 1)
    y el pipeline lo leyó como "evaluó y encontró defectos" porque ese también
    era 1. El job salió verde sin haber evaluado nada. Ningún código propio
    puede valer 1.
    """
    import runner
    propios = {runner.SALIDA_SIN_DEFECTOS, runner.SALIDA_ERROR_ARNES, runner.SALIDA_CON_DEFECTOS}
    assert 1 not in propios
    assert len(propios) == 3
    assert runner.SALIDA_SIN_DEFECTOS == 0


# ------------------------------------------------- qué se reintenta y qué no

@pytest.mark.parametrize("mensaje,reintentable", [
    ("Error code: 429 - rate limit", True),
    ("Error code: 503 - service unavailable", True),
    ("connection reset by peer", True),           # red: sin código, se reintenta
    # El 400 por JSON depende del muestreo. Tratarlo como fatal tumbó una
    # corrida real de CI por UNA generación mala de un modelo que había emitido
    # cientos de dictámenes válidos.
    ("Error code: 400 - Failed to validate JSON", True),
    ("Error code: 401 - invalid api key", False),
    ("Error code: 404 - model not found", False),
    ("Error code: 400 - invalid request", False),
])
def test_solo_se_reintenta_lo_que_puede_cambiar(mensaje, reintentable):
    from llm_client import _es_reintentable
    assert _es_reintentable(Exception(mensaje)) is reintentable


def test_el_400_de_json_sistematico_dice_que_el_modelo_no_sirve_de_juez():
    d = _diagnostico(Exception("Error code: 400 - Failed to validate JSON. Please try again"),
                     "groq", "openai/gpt-oss-safeguard-20b")
    assert "todos los intentos" in d
    assert "no sirve de juez" in d and "--modelo-juez" in d


# ------------------------------------ rescate de la generación rechazada

class _ErrorConCuerpo(Exception):
    """Imita el BadRequestError del SDK: mensaje + `body` con el detalle."""
    def __init__(self, generado):
        super().__init__("Error code: 400 - Failed to validate JSON")
        self.body = {"error": {"code": "json_validate_failed",
                               "failed_generation": generado}}


def test_se_rescata_un_dictamen_legible_que_el_proveedor_rechazo():
    """
    Groq valida el JSON con un criterio más estricto que el nuestro: un objeto
    correcto con una frase delante no le sirve, pero a nuestro extractor sí.
    """
    from llm_client import _rescatar_generacion
    texto = 'Aquí va el dictamen:\n{"coherencia": 90, "justificacion": "ok", ' \
            '"afirmaciones_factuales": [], "hallazgos": []}'
    assert _rescatar_generacion(_ErrorConCuerpo(texto)) == texto


@pytest.mark.parametrize("generado", [
    "esto no tiene JSON por ningún lado",
    '{"coherencia": 90, "justificacion": "cortado a la mit',
    "",
    None,
])
def test_no_se_rescata_lo_ilegible(generado):
    from llm_client import _rescatar_generacion
    assert _rescatar_generacion(_ErrorConCuerpo(generado)) is None


def test_el_cliente_usa_la_generacion_rescatada_en_vez_de_fallar(tmp_path):
    """Extremo a extremo por el cliente, con un SDK falso que rechaza el JSON."""
    import json as _json
    from llm_client import ClienteLLM, Mensaje

    dictamen = {"coherencia": 88, "justificacion": "bien",
                "afirmaciones_factuales": [], "hallazgos": []}

    class _Completions:
        def create(self, **_):
            raise _ErrorConCuerpo("Dictamen: " + _json.dumps(dictamen))

    class _SDK:
        chat = type("C", (), {"completions": _Completions()})()

    cliente = ClienteLLM(proveedor="groq", directorio_cache=tmp_path)
    cliente._sdk = _SDK()
    datos, _ = cliente.completar_json("s", [Mensaje("user", "x")], {"type": "object"})
    assert datos == dictamen


def test_los_reintentos_varian_la_temperatura(tmp_path):
    """
    A temperatura 0 un reintento tiende a repetir la misma generación inválida.
    El primer intento es determinista; los siguientes, no.
    """
    from llm_client import ClienteLLM, Mensaje
    temperaturas = []

    class _Completions:
        def create(self, **kw):
            temperaturas.append(kw["temperature"])
            if len(temperaturas) < 2:
                raise Exception("Error code: 400 - Failed to validate JSON")
            msg = type("M", (), {"content": '{"ok": true}'})()
            return type("R", (), {"choices": [type("Ch", (), {"message": msg})()],
                                  "usage": None})()

    class _SDK:
        chat = type("C", (), {"completions": _Completions()})()

    cliente = ClienteLLM(proveedor="groq", directorio_cache=tmp_path)
    cliente._sdk = _SDK()
    datos, _ = cliente.completar_json("s", [Mensaje("user", "x")], {"type": "object"})
    assert datos == {"ok": True}
    assert temperaturas[0] == 0 and temperaturas[1] > 0
