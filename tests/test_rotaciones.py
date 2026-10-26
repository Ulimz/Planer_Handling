from datetime import date, timedelta

from planer_handling.modelos import Empleado
from planer_handling.rotaciones import trabaja


def test_6x3_trabajan_dos_de_tres_grupos_cada_dia(conf):
    grupos = [Empleado(f"E{g}", "TL", "Fijo tiempo completo", f"6x3-{g}") for g in "ABC"]
    for d in range(18):
        dia = conf.inicio_ciclos + timedelta(days=d)
        assert sum(trabaja(e, dia, conf) for e in grupos) == 2


def test_6x3_seis_dias_seguidos_y_tres_libres(conf):
    e = Empleado("E1", "TL", "Fijo tiempo completo", "6x3-A")
    patron = [trabaja(e, conf.inicio_ciclos + timedelta(days=d), conf) for d in range(9)]
    assert patron == [True] * 6 + [False] * 3


def test_4x4_trabajan_dos_de_cuatro_grupos(conf):
    grupos = [Empleado(f"E{g}", "Mando intermedio", "Fijo tiempo completo", f"4x4-{g}") for g in "1234"]
    for d in range(16):
        assert sum(trabaja(e, conf.inicio_ciclos + timedelta(days=d), conf) for e in grupos) == 2


def test_llamamiento_y_alta_limitan_disponibilidad(conf):
    e = Empleado("E7", "Operario", "Fijo discontinuo", llamamiento=(date(2027, 4, 1), date(2027, 10, 31)))
    assert not any(trabaja(e, date(2027, 3, 1) + timedelta(days=d), conf) for d in range(20))
    futuro = Empleado("E8", "Operario", "Eventual", alta=date(2027, 6, 1))
    assert not trabaja(futuro, date(2027, 5, 31), conf)
