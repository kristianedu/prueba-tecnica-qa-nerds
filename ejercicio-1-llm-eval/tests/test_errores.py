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
