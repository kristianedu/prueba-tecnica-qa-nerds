#!/usr/bin/env python3
"""
Ejercicio 5 — Reporte consolidado.

Lee las salidas de los ejercicios 1, 2 y 3 y produce una vista única del estado
de calidad de todo el sistema evaluado, en JSON, Markdown y HTML.

Es deliberadamente tolerante a entradas ausentes: en el pipeline, un job puede
haber fallado y aun así el consolidado tiene que generarse y decir qué falta.
Un reporte que revienta cuando algo salió mal es inútil justo cuando más se
necesita.

Uso:
    python consolidar.py --entrada output --salida output
    python consolidar.py --entrada output --salida output --estricto
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Las cinco categorías de detección automática que pide el enunciado, y los
# tipos de hallazgo del Ejercicio 1 que alimentan cada una.
CATEGORIAS = {
    "Alucinaciones": ["alucinacion"],
    "Prompt Injection": ["prompt_injection", "fuga_de_prompt"],
    "Respuestas tóxicas": ["respuesta_toxica"],
    "Pérdida de contexto": ["perdida_de_contexto"],
    "Tool calling incorrecto": ["tool_calling_incorrecto"],
}


def leer_json(ruta: Path) -> Any | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ------------------------------------------------------------- Ejercicio 1

def recolectar_llm(entrada: Path) -> dict[str, Any]:
    archivos = sorted((entrada / "ejercicio-1").glob("escenario-*.json"))
    escenarios, hallazgos = [], []

    for ruta in archivos:
        d = leer_json(ruta)
        if not d:
            continue
        escenarios.append({
            "id": d.get("escenario_id"),
            "nombre": d.get("escenario"),
            "veredicto": d.get("veredicto"),
            "metricas": d.get("metricas", {}),
            "analisis": d.get("analisis", ""),
            "completada": d.get("ejecucion", {}).get("conversacion_completada"),
            "parcial": d.get("ejecucion", {}).get("evaluacion_parcial", False),
            "latencia_media_ms": d.get("ejecucion", {}).get("latencia_media_ms"),
        })
        hallazgos.extend(d.get("hallazgos", []))

    def promedio(clave: str) -> float | None:
        vals = [
            e["metricas"].get(clave) for e in escenarios
            if isinstance(e["metricas"].get(clave), (int, float))
        ]
        return round(sum(vals) / len(vals), 1) if vals else None

    completadas = sum(1 for e in escenarios if e["completada"])
    return {
        "disponible": bool(escenarios),
        "escenarios": escenarios,
        "hallazgos": hallazgos,
        "totales": {
            "escenarios": len(escenarios),
            "pass": sum(1 for e in escenarios if e["veredicto"] == "PASS"),
            "warn": sum(1 for e in escenarios if e["veredicto"] == "WARN"),
            "fail": sum(1 for e in escenarios if e["veredicto"] == "FAIL"),
            "coherencia_promedio": promedio("coherence_score"),
            "retencion_contexto_promedio": promedio("context_retention"),
            "tasa_alucinacion_promedio": promedio("hallucination_rate"),
            "seguridad_promedio": promedio("security_score"),
            "tasa_conversaciones_completadas": (
                round(completadas / len(escenarios) * 100) if escenarios else None
            ),
            "evaluacion_parcial": any(e["parcial"] for e in escenarios),
        },
    }


# --------------------------------------------------------- Ejercicios 2 y 3

def _aplanar_specs(nodo: dict[str, Any], acumulado: list[dict[str, Any]]) -> None:
    """El reporte JSON de Playwright anida suites dentro de suites."""
    for spec in nodo.get("specs", []):
        for prueba in spec.get("tests", []):
            resultados = prueba.get("results", [])
            estado = prueba.get("status") or (resultados[-1]["status"] if resultados else "unknown")
            acumulado.append({
                "titulo": spec.get("title", ""),
                "archivo": nodo.get("file", ""),
                "proyecto": prueba.get("projectName", ""),
                "estado": estado,
                "duracion_ms": sum(r.get("duration", 0) for r in resultados),
            })
    for hija in nodo.get("suites", []):
        _aplanar_specs(hija, acumulado)


def recolectar_playwright(entrada: Path) -> dict[str, dict[str, Any]]:
    """
    Lee TODOS los archivos de resultados de Playwright y los fusiona.

    Cada project escribe el suyo (`playwright-api.json`, `playwright-ui.json`)
    precisamente para que al juntar los artefactos de jobs distintos ninguno
    sobrescriba al otro.
    """
    pruebas: list[dict[str, Any]] = []
    for ruta in sorted(entrada.glob("playwright*.json")):
        datos = leer_json(ruta)
        if not datos:
            continue
        for suite in datos.get("suites", []):
            _aplanar_specs(suite, pruebas)
    if not pruebas:
        return {}

    por_proyecto: dict[str, dict[str, Any]] = {}
    for p in pruebas:
        proyecto = p["proyecto"] or "desconocido"
        r = por_proyecto.setdefault(
            proyecto,
            {"total": 0, "pass": 0, "fail": 0, "omitidas": 0,
             "duracion_ms": 0, "fallidas": []},
        )
        r["total"] += 1
        r["duracion_ms"] += p["duracion_ms"]
        if p["estado"] in ("expected", "passed"):
            r["pass"] += 1
        elif p["estado"] in ("skipped",):
            r["omitidas"] += 1
        else:
            r["fail"] += 1
            r["fallidas"].append(p["titulo"])

    for r in por_proyecto.values():
        r["duracion_media_ms"] = round(r["duracion_ms"] / r["total"], 1) if r["total"] else 0
    return por_proyecto


def recolectar_chatbot(entrada: Path) -> dict[str, Any] | None:
    return leer_json(entrada / "ejercicio-3" / "metricas-chatbot.json")


# ------------------------------------------------------------ consolidación

def detectar_transversal(hallazgos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Detección automática por categoría, transversal a todos los ejercicios.

    Las categorías sin ningún check que las alimente se reportan como NO
    EVALUADAS, no como cero. Un cero significa "se buscó y no había"; decir cero
    cuando en realidad no se midió nada es mentir con estadística.
    """
    por_tipo: dict[str, int] = {}
    for h in hallazgos:
        por_tipo[h.get("tipo", "?")] = por_tipo.get(h.get("tipo", "?"), 0) + 1

    resultado = {}
    for categoria, tipos in CATEGORIAS.items():
        detecciones = sum(por_tipo.get(t, 0) for t in tipos)
        if categoria == "Tool calling incorrecto":
            # Honestidad metodológica: al asistente bajo prueba no se le
            # entregaron herramientas, así que no hay tool calling que evaluar.
            # Reportar 0 aquí insinuaría que se midió y salió limpio.
            resultado[categoria] = {
                "detecciones": None,
                "evaluado": False,
                "nota": "No evaluado: el asistente bajo prueba no expone herramientas.",
            }
        else:
            resultado[categoria] = {
                "detecciones": detecciones,
                "evaluado": True,
                "tipos": {t: por_tipo.get(t, 0) for t in tipos},
            }
    return resultado


def construir(entrada: Path) -> dict[str, Any]:
    llm = recolectar_llm(entrada)
    pw = recolectar_playwright(entrada)
    chatbot = recolectar_chatbot(entrada)

    api = pw.get("api")
    ui = pw.get("ui")

    casos_total = casos_ok = 0
    for bloque in (api, ui):
        if bloque:
            casos_total += bloque["total"]
            casos_ok += bloque["pass"]
    if llm["disponible"]:
        casos_total += llm["totales"]["escenarios"]
        casos_ok += llm["totales"]["pass"]

    hallazgos = llm["hallazgos"]
    return {
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ejercicio_1_llm": llm,
        "ejercicio_2_api": api,
        "ejercicio_3_chatbot": {"pruebas": ui, "metricas": chatbot},
        "deteccion_automatica": detectar_transversal(hallazgos),
        "metricas_globales": {
            "casos_totales": casos_total,
            "casos_pass": casos_ok,
            "casos_fail": casos_total - casos_ok,
            "tasa_exito_pct": round(casos_ok / casos_total * 100, 1) if casos_total else None,
            "hallazgos_totales": len(hallazgos),
            "hallazgos_criticos": sum(1 for h in hallazgos if h.get("severidad") == "critica"),
            "tiempo_respuesta_api_ms": api["duracion_media_ms"] if api else None,
            "tiempo_respuesta_chatbot_ms": (
                chatbot.get("tiempo_respuesta_ms") if isinstance(chatbot, dict) else None
            ),
        },
        "faltantes": [
            nombre for nombre, presente in [
                ("ejercicio-1 (evaluación LLM)", llm["disponible"]),
                ("ejercicio-2 (API)", api is not None),
                ("ejercicio-3 (chatbot)", ui is not None),
            ] if not presente
        ],
    }


# --------------------------------------------------------------- Markdown

def _semaforo(v: str | None) -> str:
    return {"PASS": "🟢 PASS", "WARN": "🟡 WARN", "FAIL": "🔴 FAIL"}.get(v or "", "⚪ n/d")


def _o(valor: Any, sufijo: str = "") -> str:
    return "n/d" if valor is None else f"{valor}{sufijo}"


def render_markdown(r: dict[str, Any]) -> str:
    g = r["metricas_globales"]
    L: list[str] = [
        "# Reporte consolidado — Prueba Técnica QA",
        "",
        f"Generado: `{r['generado_utc']}`",
        "",
        "## Resumen global",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Casos ejecutados | {g['casos_totales']} |",
        f"| Casos en verde | {g['casos_pass']} |",
        f"| Casos en rojo | {g['casos_fail']} |",
        f"| Tasa de éxito | {_o(g['tasa_exito_pct'], '%')} |",
        f"| Hallazgos detectados | {g['hallazgos_totales']} ({g['hallazgos_criticos']} críticos) |",
        f"| Tiempo medio por caso de API | {_o(g['tiempo_respuesta_api_ms'], ' ms')} |",
        f"| Tiempo de respuesta del chatbot | {_o(g['tiempo_respuesta_chatbot_ms'], ' ms')} |",
        "",
    ]

    if r["faltantes"]:
        L += [
            "> **Aviso:** no se encontraron resultados de "
            + ", ".join(r["faltantes"])
            + ". El reporte se generó con lo disponible.",
            "",
        ]

    # ------ Ejercicio 1
    llm = r["ejercicio_1_llm"]
    L += ["## Ejercicio 1 — Evaluación conversacional", ""]
    if not llm["disponible"]:
        L += ["_Sin resultados._", ""]
    else:
        t = llm["totales"]
        L += [
            "| Escenario | Veredicto | Coherencia | Contexto | Alucinación | Seguridad |",
            "|---|---|---|---|---|---|",
        ]
        for e in llm["escenarios"]:
            m = e["metricas"]
            L.append(
                f"| {e['id']}. {e['nombre']} | {_semaforo(e['veredicto'])} "
                f"| {_o(m.get('coherence_score'))} | {_o(m.get('context_retention'), '%')} "
                f"| {_o(m.get('hallucination_rate'), '%')} | {_o(m.get('security_score'), '%')} |"
            )
        L += [
            "",
            f"**Promedios** — coherencia {_o(t['coherencia_promedio'])}, "
            f"retención de contexto {_o(t['retencion_contexto_promedio'], '%')}, "
            f"tasa de alucinación {_o(t['tasa_alucinacion_promedio'], '%')}, "
            f"cumplimiento de seguridad {_o(t['seguridad_promedio'], '%')}, "
            f"conversaciones completadas {_o(t['tasa_conversaciones_completadas'], '%')}.",
            "",
        ]
        if t["evaluacion_parcial"]:
            L += [
                "> ⚠️ Evaluación **parcial**: el juez LLM no se ejecutó (proveedor `mock`), "
                "así que `coherence_score` no se midió. Los checks determinísticos "
                "—contexto, alucinación y seguridad— sí son válidos.",
                "",
            ]

    # ------ Ejercicios 2 y 3
    for titulo, bloque in [
        ("Ejercicio 2 — API", r["ejercicio_2_api"]),
        ("Ejercicio 3 — Chatbot Web", r["ejercicio_3_chatbot"]["pruebas"]),
    ]:
        L += [f"## {titulo}", ""]
        if not bloque:
            L += ["_Sin resultados._", ""]
            continue
        L += [
            f"**{bloque['pass']}/{bloque['total']} en verde** "
            f"({bloque['fail']} en rojo, {bloque['omitidas']} omitidas) — "
            f"{round(bloque['duracion_ms'] / 1000, 1)} s en total, "
            f"media de {bloque['duracion_media_ms']} ms por caso.",
            "",
        ]
        if bloque["fallidas"]:
            L += ["Casos en rojo:", ""] + [f"- {t}" for t in bloque["fallidas"]] + [""]

    cm = r["ejercicio_3_chatbot"]["metricas"]
    if cm:
        L += ["**Métricas del chatbot:**", "", "```json",
              json.dumps(cm, ensure_ascii=False, indent=2), "```", ""]

    # ------ Detección transversal
    L += [
        "## Detección automática (transversal)",
        "",
        "| Categoría | Detecciones |",
        "|---|---|",
    ]
    for categoria, d in r["deteccion_automatica"].items():
        if not d["evaluado"]:
            L.append(f"| {categoria} | ⚪ no evaluado — {d['nota']} |")
        else:
            icono = "🔴" if d["detecciones"] else "🟢"
            L.append(f"| {categoria} | {icono} {d['detecciones']} |")
    L.append("")

    return "\n".join(L)


# ------------------------------------------------------------------- HTML

def render_html(r: dict[str, Any], markdown: str) -> str:
    g = r["metricas_globales"]
    tarjetas = "".join(
        f'<div class="t"><span class="n">{v}</span><span class="e">{k}</span></div>'
        for k, v in [
            ("Casos ejecutados", g["casos_totales"]),
            ("En verde", g["casos_pass"]),
            ("En rojo", g["casos_fail"]),
            ("Tasa de éxito", _o(g["tasa_exito_pct"], "%")),
            ("Hallazgos", g["hallazgos_totales"]),
        ]
    )
    return f"""<!doctype html>
<html lang="es"><meta charset="utf-8">
<title>Reporte consolidado — Prueba Técnica QA</title>
<style>
 :root{{color-scheme:light dark}}
 body{{font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:2rem;
      max-width:60rem;margin-inline:auto;background:#fafafa;color:#1a1a1a}}
 @media(prefers-color-scheme:dark){{body{{background:#161616;color:#eee}}
   .t,pre{{background:#222!important;border-color:#333!important}}}}
 h1{{font-size:1.6rem;margin-bottom:.2rem}} h2{{margin-top:2rem;font-size:1.15rem}}
 .cards{{display:flex;flex-wrap:wrap;gap:.75rem;margin:1.5rem 0}}
 .t{{background:#fff;border:1px solid #e3e3e3;border-radius:.6rem;padding:.85rem 1.1rem;
    min-width:8rem;display:flex;flex-direction:column;gap:.15rem}}
 .n{{font-size:1.5rem;font-weight:600}} .e{{font-size:.78rem;opacity:.65}}
 pre{{background:#fff;border:1px solid #e3e3e3;border-radius:.6rem;padding:1rem;
     overflow-x:auto;white-space:pre-wrap;font:13px/1.55 ui-monospace,SFMono-Regular,monospace}}
 .meta{{opacity:.6;font-size:.85rem}}
</style>
<h1>Reporte consolidado — Prueba Técnica QA</h1>
<p class="meta">Generado {html.escape(r['generado_utc'])}</p>
<div class="cards">{tarjetas}</div>
<pre>{html.escape(markdown)}</pre>
</html>"""


# ------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Reporte consolidado de la prueba técnica")
    ap.add_argument("--entrada", type=Path, default=Path("output"))
    ap.add_argument("--salida", type=Path, default=Path("output"))
    ap.add_argument(
        "--estricto", action="store_true",
        help="devuelve código 1 si hay casos en rojo, hallazgos críticos o resultados ausentes",
    )
    args = ap.parse_args()

    if not args.entrada.exists():
        print(f"No existe el directorio de entrada: {args.entrada}", file=sys.stderr)
        return 2

    reporte = construir(args.entrada)
    markdown = render_markdown(reporte)

    args.salida.mkdir(parents=True, exist_ok=True)
    (args.salida / "reporte-consolidado.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.salida / "reporte-consolidado.md").write_text(markdown, encoding="utf-8")
    (args.salida / "reporte-consolidado.html").write_text(
        render_html(reporte, markdown), encoding="utf-8")

    g = reporte["metricas_globales"]
    print(markdown if not args.estricto else "")
    print(f"-> {args.salida}/reporte-consolidado.{{json,md,html}}")

    if not args.estricto:
        return 0

    problemas = []
    if g["casos_fail"]:
        problemas.append(f"{g['casos_fail']} caso(s) en rojo")
    if g["hallazgos_criticos"]:
        problemas.append(f"{g['hallazgos_criticos']} hallazgo(s) crítico(s)")
    if reporte["faltantes"]:
        problemas.append("faltan resultados de " + ", ".join(reporte["faltantes"]))

    if problemas:
        print("PIPELINE EN ROJO: " + "; ".join(problemas), file=sys.stderr)
        return 1
    print("PIPELINE EN VERDE: todos los casos pasaron y no hay hallazgos críticos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
