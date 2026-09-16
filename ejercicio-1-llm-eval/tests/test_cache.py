"""
Regresión de la caché.

La caché en disco es lo que hace reproducible a toda la suite, así que una clave
mal construida no produce un error visible: produce respuestas *equivocadas* que
pasan como buenas. Este archivo fija la propiedad que debe cumplir.

El bug que originó estas pruebas: la ruta del fixture no formaba parte de la
clave. En el pipeline, el paso del fixture sano llenaba la caché y la
contraprueba con el fixture defectuoso reutilizaba esas respuestas, así que los
5 escenarios "pasaban" cuando debían fallar los 5. Lo detectó la contraprueba de
CI, no las pruebas locales, porque en local se corría con --sin-cache.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_client import CacheEnDisco, ClienteLLM, Mensaje

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _cliente(fixture: str, directorio_cache: Path) -> ClienteLLM:
    return ClienteLLM(
        proveedor="mock",
        fixture_mock=str(FIXTURES / fixture),
        directorio_cache=directorio_cache,
    )


def test_fixtures_distintos_no_comparten_entrada_de_cache(tmp_path):
    """
    Dos fixtures distintos, misma petición: no pueden devolver lo mismo.

    Es la regresión del bug: si el fixture no entra en la clave, el segundo
    cliente lee lo que cacheó el primero.
    """
    contexto = {"rol": "asistente", "escenario": 2, "turno": 5}
    mensajes = [Mensaje("user", "¿Tienen app para iPhone?")]

    sano = _cliente("asistente-sano.yaml", tmp_path)
    r_sano = sano.completar("system", mensajes, contexto=contexto)

    defectuoso = _cliente("asistente-defectuoso.yaml", tmp_path)
    r_defectuoso = defectuoso.completar("system", mensajes, contexto=contexto)

    assert r_sano.texto != r_defectuoso.texto
    assert "no tenemos" in r_sano.texto.lower()
    assert "app store" in r_defectuoso.texto.lower()


def test_el_mismo_fixture_si_reutiliza_la_cache(tmp_path):
    """La contraparte: con todo igual, la caché debe funcionar de verdad."""
    contexto = {"rol": "asistente", "escenario": 1, "turno": 2}
    mensajes = [Mensaje("user", "¿Cuánto cuesta el Pro?")]

    primero = _cliente("asistente-sano.yaml", tmp_path)
    r1 = primero.completar("system", mensajes, contexto=contexto)
    assert r1.desde_cache is False

    segundo = _cliente("asistente-sano.yaml", tmp_path)
    r2 = segundo.completar("system", mensajes, contexto=contexto)
    assert r2.desde_cache is True
    assert r2.texto == r1.texto


@pytest.mark.parametrize("cambio", [
    {"modelo": "otro-modelo"},
    {"system": "otro system prompt"},
    {"max_tokens": 999},
])
def test_cualquier_cambio_en_la_peticion_cambia_la_clave(cambio):
    """Todo lo que determina la respuesta tiene que entrar en la clave."""
    base = {
        "proveedor": "mock", "modelo": "m", "system": "s",
        "mensajes": [{"role": "user", "content": "hola"}],
        "max_tokens": 100, "esquema": None, "contexto": None, "fixture": None,
    }
    assert CacheEnDisco.clave(**base) != CacheEnDisco.clave(**{**base, **cambio})
