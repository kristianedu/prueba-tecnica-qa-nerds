import json, sys
from pathlib import Path
sys.path.insert(0, "ejercicio-5-reporte")
import consolidar

def _escenario(i):
    return {"escenario_id": i, "escenario": f"E{i}", "veredicto": "PASS", "metricas": {},
            "analisis": "", "turnos": [], "hallazgos": [], "ejecucion": {"conversacion_completada": True}}

def test_dos_de_cinco_cuenta_como_ausente(tmp_path):
    d = tmp_path / "ejercicio-1"; d.mkdir()
    for i in (1, 2):
        (d / f"escenario-{i}.json").write_text(json.dumps(_escenario(i)))
    r = consolidar.construir(tmp_path)
    assert any("2 de 5" in f for f in r["faltantes"])

def test_cinco_de_cinco_esta_disponible(tmp_path):
    d = tmp_path / "ejercicio-1"; d.mkdir()
    for i in range(1, 6):
        (d / f"escenario-{i}.json").write_text(json.dumps(_escenario(i)))
    r = consolidar.construir(tmp_path)
    assert not any("ejercicio-1" in f for f in r["faltantes"])
