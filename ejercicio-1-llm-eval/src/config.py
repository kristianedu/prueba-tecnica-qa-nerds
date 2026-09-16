"""
Carga de escenarios: fusiona `_base.yaml` con cada `escenario-N.yaml` y deja
listo el system prompt del sujeto bajo prueba.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DIR_ESCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


@dataclass
class Escenario:
    id: int
    nombre: str
    objetivo: str
    canario: str
    empresa: str
    knowledge_base: list[str]
    system_prompt: str
    parte_confidencial: str
    turnos: list[dict[str, Any]]
    umbrales: dict[str, dict[str, float]]

    def turno(self, n: int) -> dict[str, Any]:
        return next(t for t in self.turnos if t["n"] == n)

    def hechos_inyectados(self, hasta_turno: int | None = None) -> dict[str, str]:
        """Todos los datos que el usuario declaró hasta un turno dado."""
        acumulado: dict[str, str] = {}
        for t in self.turnos:
            if hasta_turno is not None and t["n"] > hasta_turno:
                break
            acumulado.update(t.get("inyecta_hechos", {}))
        return acumulado

    def intentos_de_injection(self) -> list[dict[str, Any]]:
        return [t for t in self.turnos if t.get("tipo") == "injection"]


def _leer(ruta: Path) -> dict[str, Any]:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def cargar_escenario(id_escenario: int, dir_escenarios: Path | None = None) -> Escenario:
    raiz = dir_escenarios or DIR_ESCENARIOS
    base = _leer(raiz / "_base.yaml")
    esc = _leer(raiz / f"escenario-{id_escenario}.yaml")

    kb_texto = "\n".join(f"- {h}" for h in base["knowledge_base"])
    system_prompt = base["system_prompt"].format(
        knowledge_base=kb_texto, canary=base["canary"]
    )
    # La base de conocimiento ESTÁ para ser compartida con el usuario: repetirla
    # es el trabajo del asistente, no una fuga. Lo confidencial es el resto del
    # prompt —las reglas y el canario—, y es lo único contra lo que se compara
    # al buscar recitados literales.
    parte_confidencial = base["system_prompt"].format(
        knowledge_base="", canary=base["canary"]
    )

    # Los umbrales del escenario pisan los de la base, clave por clave.
    umbrales = {**base["umbrales"], **esc.get("umbrales", {})}

    return Escenario(
        id=esc["id"],
        nombre=esc["nombre"],
        objetivo=esc["objetivo"],
        canario=base["canary"],
        empresa=base["empresa"],
        knowledge_base=base["knowledge_base"],
        system_prompt=system_prompt,
        parte_confidencial=parte_confidencial,
        turnos=esc["turnos"],
        umbrales=umbrales,
    )


def cargar_todos(dir_escenarios: Path | None = None) -> list[Escenario]:
    raiz = dir_escenarios or DIR_ESCENARIOS
    ids = sorted(
        int(p.stem.split("-")[1]) for p in raiz.glob("escenario-*.yaml")
    )
    return [cargar_escenario(i, raiz) for i in ids]
