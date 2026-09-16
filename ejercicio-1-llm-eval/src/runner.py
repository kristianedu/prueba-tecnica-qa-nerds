"""
Orquestador del Ejercicio 1.

Corre un escenario completo de 6 turnos y escribe el JSON de resultado con la
estructura que pide el enunciado, más los campos que hacen la corrida auditable
(modelos usados, hallazgos con su evidencia, latencias).

Uso:
    python src/runner.py --escenario 4
    python src/runner.py --todos --proveedor anthropic
    python src/runner.py --todos --proveedor mock --fixture fixtures/asistente-defectuoso.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from config import Escenario, cargar_escenario, cargar_todos
from evaluator import metrics
from evaluator.deterministic import evaluar_turno
from evaluator.judge import Juez
from llm_client import ClienteLLM, Mensaje
from simulated_user import UsuarioSimulado

RAIZ = Path(__file__).resolve().parents[2]
DIR_SALIDA = RAIZ / "output" / "ejercicio-1"


def correr_escenario(esc: Escenario, cliente: ClienteLLM, juez: Juez,
                     usuario: UsuarioSimulado, verboso: bool = True) -> dict:
    historial: list[Mensaje] = []
    turnos_json, resultados, dictamenes = [], [], []
    latencias = []

    for cfg in sorted(esc.turnos, key=lambda t: t["n"]):
        n = cfg["n"]

        mensaje_usuario = usuario.siguiente_mensaje(cfg, historial, escenario_id=esc.id)
        historial.append(Mensaje("user", mensaje_usuario))
        turnos_json.append({"rol": "usuario", "mensaje": mensaje_usuario})

        r = cliente.completar(
            esc.system_prompt, historial, max_tokens=700,
            contexto={"rol": "asistente", "escenario": esc.id, "turno": n},
        )
        historial.append(Mensaje("assistant", r.texto))
        latencias.append(r.latencia_ms)

        # Capa 1: determinística.
        det = evaluar_turno(
            cfg, r.texto, canario=esc.canario,
            texto_confidencial=esc.parte_confidencial,
            hechos_inyectados=esc.hechos_inyectados(hasta_turno=n),
            herramientas=esc.herramientas,
            mensajes_usuario=[m.texto for m in historial if m.rol == "user"],
        )
        resultados.append(det)

        # Capa 2: juez con rúbrica.
        dic = juez.evaluar(
            turno=n, knowledge_base=esc.knowledge_base,
            historial=historial[:-1], respuesta=r.texto,
            objetivo_escenario=esc.objetivo,
        )
        dictamenes.append(dic)

        turnos_json.append({
            "rol": "asistente",
            "mensaje": r.texto,
            "evaluacion": {
                **dic.a_dict(),
                "checks": det.checks,
                "hallazgos": [h.a_dict() for h in det.hallazgos + dic.hallazgos],
            },
            "latencia_ms": round(r.latencia_ms, 1),
        })

        if verboso:
            marca = "✗" if (det.hallazgos or dic.hallazgos) else "✓"
            print(f"    turno {n} {marca}  {len(det.hallazgos) + len(dic.hallazgos)} hallazgo(s)")

    todos = [h for d in resultados for h in d.hallazgos] + [h for d in dictamenes for h in d.hallazgos]
    m = metrics.calcular(resultados, dictamenes, turnos_esperados=len(esc.turnos))
    v, analisis = metrics.veredicto(m, todos, esc.umbrales)

    return {
        "escenario": esc.nombre,
        "escenario_id": esc.id,
        "objetivo": esc.objetivo,
        "turnos": turnos_json,
        "metricas": m.a_dict(),
        "veredicto": v,
        "analisis": analisis,
        "hallazgos": [h.a_dict() for h in todos],
        "ejecucion": {
            "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proveedor": cliente.proveedor,
            "modelo_asistente": cliente.modelo,
            "modelo_juez": juez.modelo or cliente.modelo,
            "umbrales": esc.umbrales,
            "conversacion_completada": m.conversacion_completada,
            "evaluacion_parcial": m.evaluacion_parcial,
            "latencia_media_ms": round(sum(latencias) / len(latencias), 1) if latencias else 0,
        },
    }


def _ruta_legible(ruta: Path) -> str:
    """
    Ruta relativa al repositorio cuando se puede, absoluta cuando no.

    `--salida` acepta cualquier destino, incluido uno fuera del repositorio (la
    contraprueba del pipeline escribe en un temporal). Sin esta salvaguarda,
    `relative_to` lanza ValueError y el runner muere DESPUÉS de haber evaluado
    correctamente: el fallo no está en la evaluación sino en imprimir el
    resultado, que es el peor sitio donde puede estar.
    """
    try:
        return str(ruta.relative_to(RAIZ))
    except ValueError:
        return str(ruta)


def main() -> int:
    load_dotenv(RAIZ / ".env")
    ap = argparse.ArgumentParser(description="Evaluación conversacional de agentes LLM")
    ap.add_argument("--escenario", type=int, help="ID del escenario (1-5)")
    ap.add_argument("--todos", action="store_true", help="correr los 5 escenarios")
    ap.add_argument("--proveedor", help="anthropic | groq | openai | mock")
    ap.add_argument("--modelo", help="modelo del asistente")
    ap.add_argument("--modelo-juez", help="modelo del juez")
    ap.add_argument("--fixture", help="fixture del mock")
    ap.add_argument("--sin-cache", action="store_true")
    ap.add_argument("--listar-modelos", action="store_true",
                    help="consulta al proveedor qué modelos ofrece y termina")
    ap.add_argument("--salida", type=Path, default=DIR_SALIDA)
    args = ap.parse_args()

    if args.listar_modelos:
        cliente = ClienteLLM(proveedor=args.proveedor)
        print(f"\nModelos disponibles en {cliente.proveedor}:\n")
        for m in cliente.listar_modelos():
            print(f"  {m}")
        print()
        return 0

    if not args.todos and args.escenario is None:
        ap.error("indica --escenario N o --todos")

    cliente = ClienteLLM(
        proveedor=args.proveedor, modelo=args.modelo,
        cache=not args.sin_cache, fixture_mock=args.fixture,
    )
    juez = Juez(cliente, modelo=args.modelo_juez or os.getenv("JUDGE_MODEL") or cliente.modelo)
    usuario = UsuarioSimulado(cliente)

    escenarios = cargar_todos() if args.todos else [cargar_escenario(args.escenario)]
    args.salida.mkdir(parents=True, exist_ok=True)

    print(f"\nProveedor: {cliente.proveedor}  |  asistente: {cliente.modelo}  |  juez: {juez.modelo}\n")
    resumen = []
    for esc in escenarios:
        print(f"  Escenario {esc.id}: {esc.nombre}")
        datos = correr_escenario(esc, cliente, juez, usuario)
        destino = args.salida / f"escenario-{esc.id}.json"
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    -> {datos['veredicto']}  {datos['metricas']}")
        print(f"    -> {_ruta_legible(destino)}\n")
        resumen.append((esc.id, esc.nombre, datos["veredicto"]))

    print("  " + "-" * 56)
    for i, nombre, v in resumen:
        print(f"  {i}. {nombre:34s} {v}")
    fallidos = sum(1 for _, _, v in resumen if v == "FAIL")
    print(f"  {len(resumen) - fallidos}/{len(resumen)} escenarios sin FAIL\n")
    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
