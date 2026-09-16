"""
Cliente de LLM del motor de evaluación.

Tres responsabilidades:

1. Esconder al proveedor detrás de una sola interfaz. El resto del código nunca
   sabe con cuál de los proveedores está hablando.

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
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROVEEDORES = ("groq", "anthropic", "openai")

# Claude 4.6 en adelante eliminó los parámetros de muestreo: mandarle
# `temperature` a esos modelos devuelve un HTTP 400. Haiku 4.5 y anteriores sí
# lo aceptan. Para los que no, la reproducibilidad la aporta la caché, no el
# muestreo.
_SIN_TEMPERATURA = (
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-fable-5", "claude-mythos-5",
)


# Hasta cuánto se espera a un límite por minuto antes de darse por vencido.
# Los límites de tokens por minuto se reponen en menos de 60 s; lo que pide
# esperar más que esto es una cuota diaria, y ahí esperar no arregla nada.
ESPERA_MAXIMA_S = 75.0


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

    def resumen(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "proveedor": self.proveedor,
            "latencia_ms": round(self.latencia_ms, 1),
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "desde_cache": self.desde_cache,
        }


class CacheEnDisco:
    """Caché de respuestas indexada por el hash de la petición completa."""

    def __init__(self, directorio: str | Path, activa: bool = True,
                 refrescar: bool = False):
        self.dir = Path(directorio)
        self.activa = activa
        # `refrescar` ignora lo guardado pero SÍ escribe: fuerza llamadas nuevas
        # y deja esa corrida como base para reevaluar después sin pagar. Apagar
        # la caché del todo (activa=False) hacía que una corrida real de seis
        # minutos no quedara en ningún sitio, y la siguiente "reevaluación"
        # volviera a llamar al modelo y diera otros números.
        self.refrescar = refrescar
        if self.activa:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def clave(**partes: Any) -> str:
        canonico = json.dumps(partes, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:32]

    def leer(self, clave: str) -> dict[str, Any] | None:
        if not self.activa or self.refrescar:
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
        refrescar: bool = False,
        directorio_cache: str | Path = ".llm-cache",
        reintentos: int = 3,
    ):
        self.proveedor = (proveedor or os.getenv("LLM_PROVIDER", "groq")).lower()
        if self.proveedor not in PROVEEDORES:
            raise ErrorLLM(
                f"Proveedor desconocido: {self.proveedor!r}. "
                f"Opciones: {', '.join(PROVEEDORES)}"
            )
        self.modelo = modelo or os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
        self.reintentos = reintentos
        self.cache = CacheEnDisco(directorio_cache, activa=cache, refrescar=refrescar)
        self._sdk: Any = None

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
        )
        if (guardado := self.cache.leer(clave)) is not None:
            return RespuestaLLM(**{**guardado, "desde_cache": True})

        inicio = time.perf_counter()
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            try:
                texto, t_in, t_out = self._llamar(
                    system, mensajes, modelo, max_tokens, esquema
                )
                break
            except Exception as exc:                      # noqa: BLE001
                ultimo_error = exc
                espera = segundos_de_espera(exc)
                agotado = intento == self.reintentos - 1

                # Hay dos clases de límite y se tratan al revés:
                #
                #   - Por minuto: el proveedor pide segundos. Esperarlos
                #     funciona, y es lo normal en una corrida larga —el juez
                #     consume varios miles de tokens por turno y los límites
                #     por minuto son estrechos—. Se espera lo que pide y se
                #     reintenta.
                #
                #   - Cuota diaria: pide minutos u horas. Esperar ahí bloquearía
                #     la corrida sin arreglar nada, así que se corta de
                #     inmediato con un diagnóstico que diga qué hacer.
                if espera is not None and espera <= ESPERA_MAXIMA_S and not agotado:
                    time.sleep(espera + 1)               # +1s de margen
                    continue

                if agotado or (espera is not None and espera > ESPERA_MAXIMA_S):
                    raise ErrorLLM(
                        f"{self.proveedor}/{modelo} falló"
                        + (f" tras {intento + 1} intento(s)" if espera is None else "")
                        + f": {exc}{_diagnostico(exc, self.proveedor, modelo)}"
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
        esquema: dict[str, Any] | None,
    ) -> tuple[str, int, int]:
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
        return texto, r.usage.input_tokens, r.usage.output_tokens

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
        )


def segundos_de_espera(exc: Exception) -> float | None:
    """
    Segundos que el proveedor pide esperar, si lo dice en el mensaje.

    Groq responde a un 429 con "Please try again in 6m36.576s". Saberlo permite
    distinguir un pico pasajero —que sí conviene reintentar— de una cuota diaria
    agotada, donde reintentar es tirar peticiones a la basura.
    """
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(exc))
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _diagnostico(exc: Exception, proveedor: str, modelo: str) -> str:
    """
    Explica qué hacer, según la causa real.

    El diagnóstico se elige por el tipo de fallo, no por si la palabra "model"
    aparece en el texto: el mensaje de un límite de cuota también la contiene, y
    sugerir "consulta los modelos disponibles" ante un 429 manda a quien lo lee
    en la dirección equivocada.
    """
    texto = str(exc)
    bajo = texto.lower()

    if "tokens per day" in bajo or "tpd" in bajo:
        usado = re.search(r"Limit (\d+), Used (\d+)", texto)
        detalle = f" Llevas {usado.group(2)} de {usado.group(1)} tokens." if usado else ""
        return (
            f"\n\nCuota DIARIA de tokens agotada para {modelo}.{detalle}"
            "\nOpciones: esperar al reinicio diario, usar otro modelo como juez"
            f"\n(--modelo-juez), o correr sin --sin-cache para reutilizar las"
            "\nrespuestas ya guardadas."
        )
    if "rate_limit" in bajo or "429" in texto:
        espera = segundos_de_espera(exc)
        cuando = f" Reintenta en {espera:.0f} s." if espera else ""
        return f"\n\nLímite de peticiones por minuto.{cuando}"
    if any(p in bajo for p in ("not found", "does not exist", "decommission", "invalid model")):
        return (
            "\n\nEse modelo no existe o fue retirado. Consulta los disponibles con:"
            f"\n  python src/runner.py --listar-modelos --proveedor {proveedor}"
        )
    if any(p in bajo for p in ("api key", "unauthorized", "401", "authentication")):
        return (
            f"\n\nCredencial ausente o inválida. Revisa {proveedor.upper()}_API_KEY en .env"
        )
    return ""


def _recortar_json(texto: str) -> str:
    """Extrae el objeto JSON aunque venga envuelto en ```json ... ```."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.split("```")[1]
        if limpio.startswith("json"):
            limpio = limpio[4:]
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    return limpio[inicio:fin + 1] if inicio != -1 and fin != -1 else limpio
