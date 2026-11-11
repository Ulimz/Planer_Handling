"""Plantilla ficticia con los porcentajes de una real: se vuelve a leer y salen los mismos porcentajes."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import plantilla_ficticia as pf          # noqa: E402
import porcentajes_plantilla as pp       # noqa: E402
from planer_handling.archivo import exportar_cuadrante   # noqa: E402
from planer_handling.configuracion import Configuracion  # noqa: E402

PORCENTAJES = {
    "mes_referencia": "2026-11", "dias_del_mes": 30, "total": 40, "funciones": {
        "PCP": {"personas": 30, "contratos": {"TP": 0.8, "TC": 0.2}, "rotaciones": {"6x3": 0.9, "irregular": 0.1},
                "posiciones": {"6x3:0": 0.5, "6x3:3": 0.5}, "fases": {"6x3:MMMTTT": 1.0},
                "capacitaciones": {"Operario": 1.0, "Cintero": 1.0, "Carretero": 0.6},
                "turnos_manana": {"06:00-11:00": 0.7, "06:00-14:00": 0.3},
                "turnos_tarde": {"15:00-20:00": 0.7, "14:00-22:00": 0.3},
                "horas_mes": {"TP": 100, "TC": 160}, "dias_trabajo_irregular": 12},
        "TL": {"personas": 10, "contratos": {"TC": 1.0}, "rotaciones": {"6x3": 1.0},
               "posiciones": {"6x3:6": 1.0}, "fases": {"6x3:MMMTTT": 1.0},
               "capacitaciones": {"TL": 1.0, "Operario": 1.0},
               "turnos_manana": {"06:00-14:00": 1.0}, "turnos_tarde": {"14:00-22:00": 1.0},
               "horas_mes": {"TC": 160}, "dias_trabajo_irregular": 0}}}


def test_reparto_exacto():
    assert sorted(pf.reparto(10, {"a": 0.55, "b": 0.45})) == ["a"] * 6 + ["b"] * 4
    assert len(pf.reparto(7, {"a": 1, "b": 1, "c": 1})) == 7
    assert pf.reparto(0, {"a": 1}) == []


def test_mismos_porcentajes_al_volver_a_leer(tmp_path):
    conf = Configuracion.cargar("config/base.yaml")
    filas, fichas = pf.generar(PORCENTAJES, [(2026, 11)], None, 3)
    assert [f["Código"] for f in fichas] == [f"P{i:04d}" for i in range(1, 41)]
    cuadrante = exportar_cuadrante(filas, 2026, 11, tmp_path / "c.xlsx", {})
    pd.DataFrame([{"Empleado": f["Código"], "Contrato": f["Contrato"]} for f in fichas]).to_excel(
        tmp_path / "contratos.xlsx", index=False)
    pf.formacion(fichas, conf).to_excel(tmp_path / "formacion.xlsx", index=False)
    obtenido = pp.calcular(cuadrante, 2026, 11, conf, tmp_path / "contratos.xlsx", tmp_path / "formacion.xlsx")
    pcp = obtenido["funciones"]["PCP"]
    assert obtenido["total"] == 40 and pcp["personas"] == 30
    assert pcp["contratos"] == {"TP": 0.8, "TC": 0.2}
    assert pcp["rotaciones"] == {"6x3": 0.9, "irregular": 0.1}
    assert pcp["capacitaciones"]["Carretero"] == 0.6
    assert obtenido["funciones"]["TL"]["horas_mes"]["TC"] >= 18 * 8     # 6x3 con turnos de 8 h
    assert pcp["horas_mes"]["TP"] < 120                             # los parciales con turnos cortos


def test_la_rotacion_sigue_de_un_mes_al_siguiente():
    filas, _ = pf.generar(PORCENTAJES, [(2026, 10), (2026, 11)], None, 3)
    tl = next(f for f in filas if f.funcion == "TL")
    trabajados = [d for d in sorted(tl.jornadas)]
    # 6x3 sin saltos al cambiar de mes: nunca más de 6 días seguidos ni menos de 3 de descanso.
    seguidos, maximo = 1, 1
    for a, b in zip(trabajados, trabajados[1:]):
        seguidos = seguidos + 1 if (b - a).days == 1 else 1
        maximo = max(maximo, seguidos)
        assert (b - a).days in (1, 4)
    assert maximo == 6
