"""
Orquestador del Ejercicio 1.

Corre un escenario completo de 6 turnos y escribe el JSON de resultado con la
estructura que pide el enunciado, más los campos que hacen la corrida auditable
(modelos usados, hallazgos con su evidencia, latencias).

Uso:
    python src/runner.py --escenario 4
    python src/runner.py --todos --proveedor groq
    python src/runner.py --listar-modelos --proveedor groq
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
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


def _envolver(texto: str, sangria: str = " " * 15, ancho: int = 92) -> str:
    """Texto legible en terminal, respetando los saltos de línea propios."""
    lineas = []
    for parrafo in texto.strip().splitlines():
        lineas.extend(
            textwrap.wrap(parrafo, width=ancho - len(sangria)) or [""]
        )
    return f"\n{sangria}".join(lineas)


def _imprimir_turno(n: int, mensaje_usuario: str, respuesta: str,
                    det, dic, latencia_ms: float) -> None:
    """
    Vuelca un turno completo: qué se preguntó, qué se respondió y qué dictaminó
    cada capa del evaluador.

    Es lo que hace útil trabajar escenario por escenario: sin ver la respuesta
    no se puede distinguir un defecto del modelo de un falso positivo del
    evaluador, que es justo la distinción que más cuesta y más importa.
    """
    print(f"\n  ┌─ turno {n} " + "─" * 66)
    print(f"  │ USUARIO    {_envolver(mensaje_usuario)}")
    print(f"  │ ASISTENTE  {_envolver(respuesta)}")

    # Los checks con prefijo `info:` describen lo que ocurrió, no si estuvo
    # bien. Se muestran aparte para que un ✗ siempre signifique un fallo.
    aserciones = {k: v for k, v in det.checks.items() if not k.startswith("info:")}
    informativos = {k[5:]: v for k, v in det.checks.items() if k.startswith("info:")}

    if aserciones:
        marcas = "  ".join(
            f"{'✓' if ok else '✗'} {nombre}" for nombre, ok in sorted(aserciones.items())
        )
        print(f"  │ checks     {_envolver(marcas)}")
    if informativos:
        datos = "  ".join(
            f"{nombre}: {'sí' if valor else 'no'}" for nombre, valor in sorted(informativos.items())
        )
        print(f"  │ info       {_envolver(datos)}")

    print(f"  │ coherencia {dic.coherencia} — {_envolver(dic.justificacion)}")

    sin_respaldo = [a for a in dic.afirmaciones if not a.respaldada_por_kb]
    for a in sin_respaldo:
        print(f"  │ ⚠ fuera de la base de conocimiento: {_envolver(a.afirmacion)}")
    if dic.citas_descartadas:
        print(f"  │ {dic.citas_descartadas} hallazgo(s) del juez descartado(s) por citar mal")

    for h in det.hallazgos + dic.hallazgos:
        print(f"  │ ✗ [{h.severidad}] {h.tipo}: {_envolver(h.descripcion)}")
    if not (det.hallazgos or dic.hallazgos) and not sin_respaldo:
        print("  │ ✓ sin hallazgos")
    print(f"  └─ {latencia_ms:.0f} ms")


def correr_escenario(esc: Escenario, cliente: ClienteLLM, juez: Juez,
                     usuario: UsuarioSimulado, verboso: bool = True,
                     detalle: bool = False) -> dict:
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

        if detalle:
            _imprimir_turno(n, mensaje_usuario, r.texto, det, dic, r.latencia_ms)
        elif verboso:
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


def mostrar_guardado(id_escenario: int, dir_salida: Path) -> int:
    """
    Imprime la conversación de un escenario ya evaluado, leyéndola del JSON.

    No llama al modelo ni necesita credenciales: es para revisar una entrega ya
    hecha. Quien evalúe este proyecto debería poder leer las seis conversaciones
    sin configurar nada ni gastar llamadas.
    """
    archivo = dir_salida / f"escenario-{id_escenario}.json"
    if not archivo.exists():
        print(f"No existe {archivo}. Corre primero la evaluación.", file=sys.stderr)
        return 2

    d = json.loads(archivo.read_text(encoding="utf-8"))
    ej = d.get("ejecucion", {})

    print(f"\n  Escenario {d['escenario_id']}: {d['escenario']}")
    print(f"  Objetivo: {d['objetivo']}")
    print(f"  {ej.get('proveedor')} · asistente {ej.get('modelo_asistente')} "
          f"· juez {ej.get('modelo_juez')} · {ej.get('fecha_utc')}")

    pares = [d["turnos"][i:i + 2] for i in range(0, len(d["turnos"]), 2)]
    for n, par in enumerate(pares, 1):
        usuario, asistente = par[0], par[1]
        ev = asistente.get("evaluacion", {})
        print(f"\n  ┌─ turno {n} de {len(pares)} " + "─" * 58)
        print(f"  │ USUARIO    {_envolver(usuario['mensaje'])}")
        print(f"  │ ASISTENTE  {_envolver(asistente['mensaje'])}")
        print(f"  │ coherencia {ev.get('coherencia')} — {_envolver(str(ev.get('justificacion', '')))}")
        for h in ev.get("hallazgos", []):
            print(f"  │ ✗ [{h['severidad']}] {h['tipo']}: {_envolver(h['descripcion'])}")
        if not ev.get("hallazgos"):
            print("  │ ✓ sin hallazgos")
        print(f"  └─ {asistente.get('latencia_ms')} ms")

    print(f"\n  Veredicto: {d['veredicto']}  {json.dumps(d['metricas'], ensure_ascii=False)}")
    print(f"  {_envolver(d['analisis'], sangria='  ')}\n")
    return 0


def main() -> int:
    load_dotenv(RAIZ / ".env")
    ap = argparse.ArgumentParser(description="Evaluación conversacional de agentes LLM")
    ap.add_argument("--escenario", type=int, help="ID del escenario (1-5)")
    ap.add_argument("--todos", action="store_true", help="correr los 5 escenarios")
    ap.add_argument("--proveedor", help="groq | anthropic | openai")
    ap.add_argument("--modelo", help="modelo del asistente")
    ap.add_argument("--modelo-juez", help="modelo del juez")
    ap.add_argument("--sin-cache", action="store_true")
    ap.add_argument("--detalle", action="store_true",
                    help="muestra la conversación completa y la evaluación de cada turno")
    ap.add_argument("--ver", type=int, metavar="N",
                    help="muestra la conversación de un escenario ya evaluado, "
                         "leyéndola del JSON (sin credenciales ni llamadas)")
    ap.add_argument("--listar-modelos", action="store_true",
                    help="consulta al proveedor qué modelos ofrece y termina")
    ap.add_argument("--salida", type=Path, default=DIR_SALIDA)
    args = ap.parse_args()

    if args.ver is not None:
        return mostrar_guardado(args.ver, args.salida)

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
        cache=not args.sin_cache,
    )
    juez = Juez(cliente, modelo=args.modelo_juez or os.getenv("JUDGE_MODEL") or cliente.modelo)
    usuario = UsuarioSimulado(cliente)

    escenarios = cargar_todos() if args.todos else [cargar_escenario(args.escenario)]
    args.salida.mkdir(parents=True, exist_ok=True)

    print(f"\nProveedor: {cliente.proveedor}  |  asistente: {cliente.modelo}  |  juez: {juez.modelo}\n")
    resumen = []
    for esc in escenarios:
        print(f"  Escenario {esc.id}: {esc.nombre}")
        datos = correr_escenario(esc, cliente, juez, usuario, detalle=args.detalle)
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
