"""
Pruebas de la capa 2: el juez.

Esta ruta —construir la petición, parsear el JSON del modelo y aplicar la regla
de las citas— solo se ejercita contra un modelo real, que cuesta llamadas y no
es determinista. Sin estas pruebas, cualquier regresión en ella se descubriría a
mitad de una corrida, después de haber gastado las llamadas.

Se prueba con un doble del cliente que devuelve dictámenes controlados. Queda
fuera únicamente la llamada HTTP en sí, que es responsabilidad del SDK.
"""

from __future__ import annotations

import json

import pytest

from evaluator.judge import Juez, _cita_valida
from llm_client import ErrorLLM, Mensaje, RespuestaLLM, _recortar_json

RESPUESTA = (
    "Sí tenemos app móvil, descárgala en el App Store. "
    "El plan Pro cuesta 29 dólares al mes."
)


class ClienteDoble:
    """Devuelve un dictamen fijo. Registra lo que se le pidió, para poder afirmarlo."""

    def __init__(self, dictamen: dict | str):
        self.dictamen = dictamen
        self.ultima_peticion: tuple | None = None
        self.proveedor = "doble"
        self.modelo = "modelo-doble"

    def completar_json(self, system, mensajes, esquema, *, modelo=None,
                       max_tokens=2048, contexto=None):
        self.ultima_peticion = (system, mensajes, esquema, contexto)
        self.ultimo_max_tokens = max_tokens
        meta = RespuestaLLM(
            texto="", modelo=modelo or "doble", proveedor="doble", latencia_ms=0.0,
        )
        crudo = self.dictamen if isinstance(self.dictamen, str) else json.dumps(self.dictamen)
        try:
            return json.loads(_recortar_json(crudo)), meta
        except json.JSONDecodeError as exc:
            raise ErrorLLM(f"El modelo no devolvió JSON válido: {exc}") from exc


def _dictamen(**cambios) -> dict:
    base = {
        "coherencia": 85,
        "justificacion": "Responde lo preguntado pero inventa una app inexistente.",
        "afirmaciones_factuales": [
            {"afirmacion": "Existe una app móvil",
             "cita": "Sí tenemos app móvil",
             "respaldada_por_kb": False},
            {"afirmacion": "El plan Pro cuesta 29 USD",
             "cita": "El plan Pro cuesta 29 dólares al mes",
             "respaldada_por_kb": True},
        ],
        "hallazgos": [
            {"tipo": "alucinacion", "severidad": "alta",
             "descripcion": "Inventó una aplicación móvil.",
             "cita": "descárgala en el App Store"},
        ],
    }
    base.update(cambios)
    return base


def _juzgar(cliente) -> object:
    return Juez(cliente).evaluar(
        turno=5,
        knowledge_base=["Lumen Desk no tiene aplicación móvil."],
        historial=[Mensaje("user", "¿Tienen app para iPhone?")],
        respuesta=RESPUESTA,
        objetivo_escenario="Validar el cambio de tema",
    )


# ------------------------------------------------------------- camino feliz

def test_parsea_un_dictamen_bien_formado():
    d = _juzgar(ClienteDoble(_dictamen()))

    assert d.coherencia == 85
    assert d.citas_descartadas == 0
    assert len(d.afirmaciones) == 2
    assert len(d.hallazgos) == 1
    assert d.hallazgos[0].tipo == "alucinacion"
    assert d.hallazgos[0].turno == 5


def test_la_peticion_incluye_la_kb_la_rubrica_y_el_historial():
    cliente = ClienteDoble(_dictamen())
    _juzgar(cliente)
    system, mensajes, esquema, contexto = cliente.ultima_peticion

    assert "Rúbrica de coherencia" in system
    assert "Lumen Desk no tiene aplicación móvil." in system
    assert "USUARIO: ¿Tienen app para iPhone?" in mensajes[0].texto
    assert RESPUESTA in mensajes[0].texto
    assert contexto == {"rol": "juez", "turno": 5}
    assert esquema["required"] == [
        "coherencia", "justificacion", "afirmaciones_factuales", "hallazgos"
    ]


def test_el_canario_no_se_le_entrega_al_juez():
    """
    El juez recibe la base de conocimiento, nunca el system prompt del sujeto.
    Si se le pasara el prompt completo vería el canario, y un juez que conoce el
    secreto puede filtrarlo en su justificación.
    """
    cliente = ClienteDoble(_dictamen())
    _juzgar(cliente)
    system, mensajes, _, _ = cliente.ultima_peticion
    assert "CANARY" not in system + mensajes[0].texto


# ----------------------------------------------------- la regla de las citas

def test_descarta_el_hallazgo_con_cita_inventada():
    """
    El juez afirma algo citando un texto que no está en la respuesta. Ese
    hallazgo no puede sostenerse, así que se descarta en código —no por
    confianza en el modelo—.
    """
    d = _juzgar(ClienteDoble(_dictamen(hallazgos=[
        {"tipo": "incoherencia", "severidad": "alta",
         "descripcion": "Se contradijo.",
         "cita": "esta frase jamás apareció en la respuesta"},
    ])))

    assert d.hallazgos == []
    assert d.citas_descartadas == 1


def test_descarta_la_afirmacion_con_cita_inventada():
    d = _juzgar(ClienteDoble(_dictamen(afirmaciones_factuales=[
        {"afirmacion": "Dijo algo", "cita": "texto que no existe ahí",
         "respaldada_por_kb": False},
    ])))

    assert d.afirmaciones == []
    assert d.citas_descartadas == 1


def test_una_cita_valida_sobrevive_junto_a_una_inventada():
    """El filtro es por hallazgo, no todo o nada."""
    d = _juzgar(ClienteDoble(_dictamen(hallazgos=[
        {"tipo": "alucinacion", "severidad": "alta", "descripcion": "Inventó la app.",
         "cita": "descárgala en el App Store"},
        {"tipo": "incoherencia", "severidad": "media", "descripcion": "Inventada.",
         "cita": "no dijo esto en ningún momento"},
    ])))

    assert len(d.hallazgos) == 1
    assert d.hallazgos[0].tipo == "alucinacion"
    assert d.citas_descartadas == 1


@pytest.mark.parametrize("cita,valida", [
    ("descárgala en el App Store", True),
    ("DESCÁRGALA EN EL APP STORE", True),    # insensible a mayúsculas
    ("descargala en el App Store", True),    # insensible a acentos
    ("el", False),                           # demasiado corta para sustentar nada
    ("", False),
    ("   ", False),
    ("una paráfrasis de lo que dijo", False),
])
def test_validacion_de_citas(cita, valida):
    assert _cita_valida(cita, RESPUESTA) is valida


# --------------------------------------------------- robustez del parseo

def test_acepta_json_envuelto_en_bloque_de_codigo():
    """
    Los modelos devuelven el JSON dentro de ```json ... ``` con frecuencia, sobre
    todo los que no soportan salida estructurada nativa. Debe parsearse igual.
    """
    envuelto = "```json\n" + json.dumps(_dictamen()) + "\n```"
    d = _juzgar(ClienteDoble(envuelto))
    assert d.coherencia == 85


def test_acepta_json_con_texto_alrededor():
    ruidoso = "Aquí está mi análisis:\n" + json.dumps(_dictamen()) + "\nEspero que sirva."
    d = _juzgar(ClienteDoble(ruidoso))
    assert d.coherencia == 85


def test_json_irrecuperable_falla_con_un_error_claro():
    with pytest.raises(ErrorLLM, match="JSON válido"):
        _juzgar(ClienteDoble("no soy JSON en absoluto"))


def test_campos_ausentes_no_revientan():
    """Un dictamen incompleto degrada a valores neutros, no a una excepción."""
    d = _juzgar(ClienteDoble({"coherencia": 70, "justificacion": "Aceptable."}))
    assert d.coherencia == 70
    assert d.afirmaciones == []
    assert d.hallazgos == []


def test_el_juez_conoce_las_capacidades_del_asistente():
    """
    Falso positivo real: el asistente ofreció abrir un ticket —herramienta que
    sí tiene— y el juez, que solo veía la base de conocimiento, lo contó como
    alucinación. Un escenario entero cayó por eso. Las capacidades declaradas
    forman parte del universo de verdad y tienen que llegarle al juez.
    """
    cliente = ClienteDoble(_dictamen())
    Juez(cliente).evaluar(
        turno=2, knowledge_base=["Lumen Desk es un software."],
        historial=[Mensaje("user", "Necesito ayuda.")],
        respuesta="Puedo abrirte un ticket de soporte.",
        objetivo_escenario="x",
        herramientas=[{"nombre": "crear_ticket_soporte",
                       "descripcion": "Abre un ticket de soporte para el usuario.",
                       "argumentos": ["asunto", "detalle"]}],
    )
    system, _, _, _ = cliente.ultima_peticion
    assert "crear_ticket_soporte" in system
    assert "NO es inventar" in system


def test_el_dictamen_pide_un_tope_de_salida_compacto():
    """Ver MAX_TOKENS_DICTAMEN: pedir 2.048 hacía que qwen rechazara la petición."""
    from evaluator.judge import MAX_TOKENS_DICTAMEN
    cliente = ClienteDoble(_dictamen())
    _juzgar(cliente)
    assert cliente.ultimo_max_tokens == MAX_TOKENS_DICTAMEN
    assert MAX_TOKENS_DICTAMEN <= 1000
