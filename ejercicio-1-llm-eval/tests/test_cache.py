"""
Pruebas de la caché en disco.

La caché es lo que hace reproducible a la suite y lo que evita volver a pagar
las 71 llamadas en cada corrida. Una clave mal construida no produce un error
visible: produce respuestas *equivocadas* que pasan como buenas, porque una
petición distinta recupera la entrada de otra.

De ahí que la propiedad que se fija aquí sea la más importante del módulo: todo
lo que determina la respuesta tiene que formar parte de la clave.
"""

from __future__ import annotations

import pytest

from llm_client import CacheEnDisco

BASE = {
    "proveedor": "groq",
    "modelo": "openai/gpt-oss-20b",
    "system": "Eres el asistente de soporte de Lumen Tech.",
    "mensajes": [{"role": "user", "content": "¿Cuánto cuesta el plan Pro?"}],
    "max_tokens": 700,
    "esquema": None,
}


@pytest.mark.parametrize("cambio", [
    {"proveedor": "anthropic"},
    {"modelo": "openai/gpt-oss-120b"},
    {"system": "Eres otro asistente distinto."},
    {"mensajes": [{"role": "user", "content": "¿Y el plan Básico?"}]},
    {"max_tokens": 1024},
    {"esquema": {"type": "object"}},
], ids=["proveedor", "modelo", "system", "mensajes", "max_tokens", "esquema"])
def test_cualquier_cambio_en_la_peticion_cambia_la_clave(cambio):
    assert CacheEnDisco.clave(**BASE) != CacheEnDisco.clave(**{**BASE, **cambio})


def test_la_misma_peticion_da_la_misma_clave():
    assert CacheEnDisco.clave(**BASE) == CacheEnDisco.clave(**BASE)


def test_el_orden_de_los_campos_no_altera_la_clave():
    """
    La clave se calcula sobre JSON canónico. Si dependiera del orden en que se
    pasan los campos, la caché fallaría de forma intermitente según el camino
    del código que la invoque.
    """
    invertido = dict(reversed(list(BASE.items())))
    assert CacheEnDisco.clave(**BASE) == CacheEnDisco.clave(**invertido)


def test_guarda_y_recupera(tmp_path):
    cache = CacheEnDisco(tmp_path)
    clave = CacheEnDisco.clave(**BASE)

    assert cache.leer(clave) is None
    cache.escribir(clave, {"texto": "El plan Pro cuesta 29 dólares al mes."})
    assert cache.leer(clave)["texto"] == "El plan Pro cuesta 29 dólares al mes."


def test_una_entrada_corrupta_se_trata_como_ausente(tmp_path):
    """
    Un archivo truncado —por ejemplo si se interrumpe una corrida a mitad de
    escritura— no puede tumbar la siguiente. Se trata como si no existiera y se
    vuelve a pedir al modelo.
    """
    cache = CacheEnDisco(tmp_path)
    clave = CacheEnDisco.clave(**BASE)
    (tmp_path / f"{clave}.json").write_text("{ esto no es JSON", encoding="utf-8")

    assert cache.leer(clave) is None


def test_desactivada_no_escribe_ni_lee(tmp_path):
    """`--sin-cache` tiene que forzar llamadas nuevas de verdad."""
    cache = CacheEnDisco(tmp_path, activa=False)
    clave = CacheEnDisco.clave(**BASE)

    cache.escribir(clave, {"texto": "algo"})
    assert cache.leer(clave) is None
    assert list(tmp_path.glob("*.json")) == []


def test_refrescar_ignora_lo_guardado_pero_si_escribe(tmp_path):
    """
    `--sin-cache` tiene que forzar llamadas nuevas Y guardarlas. Antes apagaba
    la caché por completo: una corrida real de seis minutos no quedaba en ningún
    sitio y la siguiente reevaluación volvía a llamar al modelo.
    """
    clave = CacheEnDisco.clave(**BASE)

    vieja = CacheEnDisco(tmp_path)
    vieja.escribir(clave, {"texto": "respuesta antigua"})

    refresco = CacheEnDisco(tmp_path, refrescar=True)
    assert refresco.leer(clave) is None                 # no reutiliza lo viejo
    refresco.escribir(clave, {"texto": "respuesta nueva"})

    despues = CacheEnDisco(tmp_path)
    assert despues.leer(clave)["texto"] == "respuesta nueva"   # y quedó guardada
