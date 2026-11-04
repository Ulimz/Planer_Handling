from datetime import date

from planer_handling.demanda import tareas_plataforma
from planer_handling.modelos import Vuelo


def test_giro_largo_se_atiende_en_dos_veces(conf):
    corto = Vuelo(date(2027, 7, 15), "XX1", "MAN", 600, "XX2", "EDI", 625)
    largo = Vuelo(date(2027, 7, 15), "XX3", "MAN", 600, "XX4", "EDI", 600 + 6 * 60)
    tareas = tareas_plataforma([corto, largo], conf)
    assert [t.tipo for t in tareas] == ["GIRO", "LLEGADA", "SALIDA"]
    assert max(t.fin - t.inicio for t in tareas) < 120
