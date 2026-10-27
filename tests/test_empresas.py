from pathlib import Path

from planer_handling import empresas
from planer_handling.configuracion import Configuracion

CONFIG = Path(__file__).resolve().parent.parent / "config"


def test_clave_de():
    assert empresas.clave_de("Jet2 · Málaga") == "jet2_malaga"


def test_diferencias_solo_lo_que_cambia():
    base = {"a": 1, "b": {"c": 2, "d": [1, 2]}}
    assert empresas.diferencias(base, {"a": 1, "b": {"c": 3, "d": [1, 2]}}) == {"b": {"c": 3}}
    assert empresas.diferencias(base, base) is None


def test_guardar_y_cargar(tmp_path):
    datos = Configuracion.cargar(CONFIG / "base.yaml").datos
    datos["pasaje"]["activo"] = True
    datos["cambios_publicado"]["preaviso_horario_completo_dias"] = 7
    datos["empresa"]["nombre"] = "Prueba"
    ruta = empresas.guardar(datos, CONFIG / "base.yaml", tmp_path, "prueba")
    texto = ruta.read_text(encoding="utf-8")
    assert "turnos:" not in texto           # lo que no cambia no se copia
    cargada = Configuracion.cargar(ruta).datos
    assert cargada["pasaje"]["activo"] is True
    assert cargada["cambios_publicado"]["preaviso_horario_completo_dias"] == 7
    assert cargada["turnos"] == datos["turnos"]
    perfiles = empresas.listar(CONFIG, tmp_path)
    propio = next(p for p in perfiles if p.clave == "prueba")
    assert propio.editable and propio.nombre == "Prueba"
    assert empresas.padre_de(ruta) == (CONFIG / "base.yaml").resolve()
    assert not next(p for p in perfiles if p.clave == "base").editable
