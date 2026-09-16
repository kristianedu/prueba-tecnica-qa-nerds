"""
Cliente de LLM del motor de evaluación.

Tres responsabilidades:

1. Esconder al proveedor detrás de una sola interfaz. El resto del código nunca
   sabe si está hablando con Anthropic, Groq, OpenAI o con el mock.

2. Cachear cada respuesta en disco. Esto es lo que hace que la segunda corrida
   sea idéntica a la primera y salga gratis. La reproducibilidad de toda la
   suite depende de esta caché, así que no es un detalle de rendimiento: es
   parte del diseño de la prueba.

3. Registrar latencia y tokens, que el reporte consolidado del Ejercicio 5
   necesita.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROVEEDORES = ("anthropic", "groq", "openai", "mock")

# Claude 4.6 en adelante eliminó los parámetros de muestreo: mandarle
# `temperature` a esos modelos devuelve un HTTP 400. Haiku 4.5 y anteriores sí
# lo aceptan. Para los que no, la reproducibilidad la aporta la caché, no el
# muestreo.
_SIN_TEMPERATURA = (
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-fable-5", "claude-mythos-5",
)


def acepta_temperatura(modelo: str) -> bool:
    return not modelo.startswith(_SIN_TEMPERATURA)


class ErrorLLM(RuntimeError):
    pass


@dataclass
class Mensaje:
    rol: str          # "user" | "assistant"
    texto: str

    def como_api(self) -> dict[str, str]:
        return {"role": self.rol, "content": self.texto}


@dataclass
class RespuestaLLM:
    texto: str
    modelo: str
    proveedor: str
    latencia_ms: float
    tokens_entrada: int = 0
    tokens_salida: int = 0
    desde_cache: bool = False
    es_stub: bool = False   # True cuando la produjo el mock, no un modelo real

    def resumen(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "proveedor": self.proveedor,
            "latencia_ms": round(self.latencia_ms, 1),
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "desde_cache": self.desde_cache,
            "es_stub": self.es_stub,
        }


class CacheEnDisco:
    """Caché de respuestas indexada por el hash de la petición completa."""

    def __init__(self, directorio: str | Path, activa: bool = True):
        self.dir = Path(directorio)
        self.activa = activa
        if self.activa:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def clave(**partes: Any) -> str:
        canonico = json.dumps(partes, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:32]

    def leer(self, clave: str) -> dict[str, Any] | None:
        if not self.activa:
            return None
        archivo = self.dir / f"{clave}.json"
        if not archivo.exists():
            return None
        try:
            return json.loads(archivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None   # caché corrupta: se trata como ausencia, no como error

    def escribir(self, clave: str, payload: dict[str, Any]) -> None:
        if not self.activa:
            return
        (self.dir / f"{clave}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class ClienteLLM:
    """Punto único de entrada para hablar con cualquier proveedor."""

    def __init__(
        self,
        proveedor: str | None = None,
        modelo: str | None = None,
        *,
        cache: bool = True,
        directorio_cache: str | Path = ".llm-cache",
        reintentos: int = 3,
        fixture_mock: str | Path | None = None,
    ):
        self.proveedor = (proveedor or os.getenv("LLM_PROVIDER", "mock")).lower()
        if self.proveedor not in PROVEEDORES:
            raise ErrorLLM(
                f"Proveedor desconocido: {self.proveedor!r}. "
                f"Opciones: {', '.join(PROVEEDORES)}"
            )
        self.modelo = modelo or os.getenv("LLM_MODEL", "claude-haiku-4-5")
        self.reintentos = reintentos
        self.cache = CacheEnDisco(directorio_cache, activa=cache)
        self._sdk: Any = None
        self._fixture_mock = fixture_mock
        self._mock_cargado: dict[str, Any] | None = None

    # ------------------------------------------------------------------ API

    def completar(
        self,
        system: str,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        max_tokens: int = 1024,
        contexto: dict[str, Any] | None = None,
    ) -> RespuestaLLM:
        """Devuelve texto libre."""
        return self._despachar(
            system, mensajes, modelo or self.modelo, max_tokens, contexto or {}, esquema=None
        )

    def completar_json(
        self,
        system: str,
        mensajes: list[Mensaje],
        esquema: dict[str, Any],
        *,
        modelo: str | None = None,
        max_tokens: int = 2048,
        contexto: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], RespuestaLLM]:
        """Devuelve JSON validado contra `esquema`. Lo usa el juez."""
        respuesta = self._despachar(
            system, mensajes, modelo or self.modelo, max_tokens, contexto or {}, esquema=esquema
        )
        try:
            datos = json.loads(_recortar_json(respuesta.texto))
        except json.JSONDecodeError as exc:
            raise ErrorLLM(
                f"El modelo no devolvió JSON válido: {exc}\n---\n{respuesta.texto[:500]}"
            ) from exc
        return datos, respuesta

    def listar_modelos(self) -> list[str]:
        """
        Modelos disponibles según el propio proveedor.

        Los catálogos cambian con frecuencia y un ID inventado falla en mitad de
        una corrida, después de haber gastado llamadas. Mejor preguntarle al
        proveedor que confiar en la memoria.
        """
        if self.proveedor == "mock":
            return ["(el proveedor mock no usa modelos)"]
        if self.proveedor == "anthropic":
            import anthropic
            return sorted(m.id for m in anthropic.Anthropic().models.list())
        if self.proveedor == "groq":
            from groq import Groq
            return sorted(m.id for m in Groq().models.list().data)
        from openai import OpenAI
        return sorted(m.id for m in OpenAI().models.list())

    # ------------------------------------------------------------- interno

    def _despachar(
        self,
        system: str,
        mensajes: list[Mensaje],
        modelo: str,
        max_tokens: int,
        contexto: dict[str, Any],
        esquema: dict[str, Any] | None,
    ) -> RespuestaLLM:
        clave = CacheEnDisco.clave(
            proveedor=self.proveedor,
            modelo=modelo,
            system=system,
            mensajes=[m.como_api() for m in mensajes],
            max_tokens=max_tokens,
            esquema=esquema,
            contexto=contexto if self.proveedor == "mock" else None,
            fixture=str(self._ruta_fixture()) if self.proveedor == "mock" else None,
        )
        if (guardado := self.cache.leer(clave)) is not None:
            return RespuestaLLM(**{**guardado, "desde_cache": True})

        inicio = time.perf_counter()
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                texto, t_in, t_out, es_stub = self._llamar(
                    system, mensajes, modelo, max_tokens, contexto, esquema
                )
                break
            except Exception as exc:                      # noqa: BLE001
                ultimo_error = exc
                if intento == self.reintentos - 1:
                    pista = ""
                    if any(p in str(exc).lower() for p in
                           ("model", "not found", "does not exist", "decommission")):
                        pista = (
                            f"\n\nSi el modelo ya no existe, consulta los disponibles con:"
                            f"\n  python src/runner.py --listar-modelos --proveedor {self.proveedor}"
                        )
                    raise ErrorLLM(
                        f"{self.proveedor}/{modelo} falló tras {self.reintentos} "
                        f"intentos: {exc}{pista}"
                    ) from exc
                time.sleep(2 ** intento)                  # 1s, 2s, 4s
        else:                                            # pragma: no cover
            raise ErrorLLM(str(ultimo_error))

        respuesta = RespuestaLLM(
            texto=texto,
            modelo=modelo,
            proveedor=self.proveedor,
            latencia_ms=(time.perf_counter() - inicio) * 1000,
            tokens_entrada=t_in,
            tokens_salida=t_out,
            es_stub=es_stub,
        )
        payload = respuesta.__dict__.copy()
        payload.pop("desde_cache", None)
        self.cache.escribir(clave, payload)
        return respuesta

    def _llamar(
        self,
        system: str,
        mensajes: list[Mensaje],
        modelo: str,
        max_tokens: int,
        contexto: dict[str, Any],
        esquema: dict[str, Any] | None,
    ) -> tuple[str, int, int, bool]:
        if self.proveedor == "mock":
            return self._llamar_mock(contexto, esquema)
        if self.proveedor == "anthropic":
            return self._llamar_anthropic(system, mensajes, modelo, max_tokens, esquema)
        return self._llamar_compatible_openai(system, mensajes, modelo, max_tokens, esquema)

    def _llamar_anthropic(self, system, mensajes, modelo, max_tokens, esquema):
        if self._sdk is None:
            import anthropic
            self._sdk = anthropic.Anthropic()

        kwargs: dict[str, Any] = {
            "model": modelo,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [m.como_api() for m in mensajes],
        }
        if acepta_temperatura(modelo):
            kwargs["temperature"] = 0
        if esquema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": esquema}}

        r = self._sdk.messages.create(**kwargs)
        texto = next((b.text for b in r.content if b.type == "text"), "")
        return texto, r.usage.input_tokens, r.usage.output_tokens, False

    def _llamar_compatible_openai(self, system, mensajes, modelo, max_tokens, esquema):
        """Groq y OpenAI comparten la forma de chat completions."""
        if self._sdk is None:
            if self.proveedor == "groq":
                from groq import Groq
                self._sdk = Groq()
            else:
                from openai import OpenAI
                self._sdk = OpenAI()

        instruccion = system
        if esquema is not None:
            instruccion += (
                "\n\nResponde ÚNICAMENTE con un objeto JSON válido que cumpla "
                f"este esquema, sin texto alrededor:\n{json.dumps(esquema, ensure_ascii=False)}"
            )
        r = self._sdk.chat.completions.create(
            model=modelo,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "system", "content": instruccion}]
                     + [m.como_api() for m in mensajes],
            **({"response_format": {"type": "json_object"}} if esquema else {}),
        )
        uso = getattr(r, "usage", None)
        return (
            r.choices[0].message.content or "",
            getattr(uso, "prompt_tokens", 0),
            getattr(uso, "completion_tokens", 0),
            False,
        )

    def _llamar_mock(self, contexto, esquema):
        """
        Respuestas pregrabadas. Sirve para dos cosas distintas:

          - correr el pipeline completo sin credenciales (demo y CI), y
          - alimentar al evaluador con respuestas MALAS a propósito, para
            comprobar que efectivamente las detecta.

        El juez no se puede simular de verdad, así que en modo mock devuelve un
        stub neutro marcado con es_stub=True. Las métricas lo propagan para que
        nadie confunda una corrida mock con una evaluación real.
        """
        rol = contexto.get("rol", "asistente")

        if rol == "juez" or esquema is not None:
            stub = {
                "coherencia": 0,
                "hallazgos": [],
                "afirmaciones_factuales": [],
                "nota": "Juez no ejecutado: el proveedor es 'mock'.",
            }
            return json.dumps(stub, ensure_ascii=False), 0, 0, True

        fixture = self._cargar_fixture()
        clave = f"escenario_{contexto.get('escenario')}"
        turno = str(contexto.get("turno"))
        try:
            return fixture[rol][clave][turno], 0, 0, True
        except KeyError as exc:
            raise ErrorLLM(
                f"El fixture mock no tiene entrada para rol={rol} "
                f"{clave} turno={turno}"
            ) from exc

    def _ruta_fixture(self) -> Path:
        return Path(
            self._fixture_mock
            or os.getenv("MOCK_FIXTURE")
            or Path(__file__).resolve().parents[1] / "fixtures" / "asistente-sano.yaml"
        ).resolve()

    def _cargar_fixture(self) -> dict[str, Any]:
        if self._mock_cargado is not None:
            return self._mock_cargado
        ruta = self._ruta_fixture()
        if not ruta.exists():
            raise ErrorLLM(f"No existe el fixture mock: {ruta}")
        self._mock_cargado = _cargar_fixture_con_herencia(ruta)
        return self._mock_cargado


def _recortar_json(texto: str) -> str:
    """Extrae el objeto JSON aunque venga envuelto en ```json ... ```."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("```")[1]
        if limpio.startswith("json"):
            limpio = limpio[4:]
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    return limpio[inicio:fin + 1] if inicio != -1 and fin != -1 else limpio


def _cargar_fixture_con_herencia(ruta: Path) -> dict[str, Any]:
    """
    Carga un fixture resolviendo `extiende:`.

    Permite que el fixture defectuoso declare SOLO los turnos que rompe y herede
    el resto del sano. Así el archivo se lee como lo que es —una lista de fallas
    plantadas— en vez de como 41 respuestas entre las que hay que buscar cuál
    está mal.
    """
    import yaml

    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    padre_ref = datos.pop("extiende", None)
    if not padre_ref:
        return datos

    padre = _cargar_fixture_con_herencia((ruta.parent / padre_ref).resolve())
    return _fusionar(padre, datos)


def _fusionar(base: dict[str, Any], encima: dict[str, Any]) -> dict[str, Any]:
    """Fusión profunda: los valores de `encima` pisan los de `base`."""
    salida = dict(base)
    for clave, valor in encima.items():
        if isinstance(valor, dict) and isinstance(salida.get(clave), dict):
            salida[clave] = _fusionar(salida[clave], valor)
        else:
            salida[clave] = valor
    return salida
