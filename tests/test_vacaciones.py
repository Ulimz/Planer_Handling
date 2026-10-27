from datetime import date

from planer_handling import vacaciones
from planer_handling.vacaciones import Solicitud


def test_normaliza_periodos():
    assert [vacaciones.normalizar_periodo(t) for t in ["JUL-1", "jul 2", "1ª quincena julio", "agosto-2", "x"]] == [
        "JUL-1", "JUL-2", "JUL-1", "AGO-2", None]


def test_elige_primero_quien_menos_puntos_tiene_y_respeta_el_cupo(conf):
    # Cupo de 1 persona por función en verano: de tres TL que piden JUL-1, se lo lleva quien menos
    # puntos tiene; en empate de puntos, el más antiguo.
    conf.datos["vacaciones"]["temporadas"] = [{"nombre": "Verano", "periodos": ["JUL-1"], "puntos": 10, "cupo": 0.01}]
    solicitudes = [Solicitud("A", "TL", 20, date(2010, 1, 1), ["JUL-1", "OCT-1"]),
                   Solicitud("B", "TL", 5, date(2020, 1, 1), ["JUL-1", "OCT-2"]),
                   Solicitud("C", "TL", 5, date(2015, 1, 1), ["JUL-1", "NOV-1"])]
    vacaciones.repartir(solicitudes, 2027, conf)
    por_nombre = {s.empleado: s for s in solicitudes}
    assert "JUL-1" in por_nombre["C"].asignados
    assert "JUL-1" not in por_nombre["A"].asignados and "JUL-1" not in por_nombre["B"].asignados
    assert all(len(s.asignados) == 2 for s in solicitudes)
    valor = vacaciones.valor_periodos(vacaciones.quincenas(2027), conf)
    assert por_nombre["C"].puntos_despues(valor) == 5 + 10 + 2      # JUL-1 (10) y NOV-1 (2 por defecto)


def test_vacaciones_como_ausencias():
    s = Solicitud("A", "TL", asignados=["FEB-2"])
    assert vacaciones.como_ausencias([s], 2027) == [("A", "TL", date(2027, 2, 16), date(2027, 2, 28))]
