from datetime import date

from planer_handling import anual
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada

from .test_mensual import OCTUBRE, _fila

def test_la_rotacion_sigue_en_el_anio_siguiente_sin_reiniciarse():
    r = anual.rotaciones_recientes([([_fila("TL", "UNO", 2)], OCTUBRE)])[0]
    assert r.patron == "6x3"
    # 1 de octubre en la posición 2 (MMMTTT---): el ciclo de 9 días sigue sin cortes.
    esperado = [(i + 2) % 9 for i in range((date(2027, 1, 1) - date(2026, 10, 1)).days, 400)]
    assert [r.dia(date(2027, 1, 1)), r.dia(date(2027, 1, 2))] == [
        "M" if esperado[0] < 3 else "T" if esperado[0] < 6 else "",
        "M" if esperado[1] < 3 else "T" if esperado[1] < 6 else ""]
    assert sum(1 for d in anual.dias_del_anio(2027) if r.dia(d)) in (242, 243, 244)


def test_baja_sin_horario_no_rompe_la_rotacion():
    fila = _fila("PCP", "BAJA", 0)
    for d in OCTUBRE[10:18]:                     # ocho días de baja, en el cuadrante sin horario
        fila.jornadas.pop(d, None)
        fila.marcas_vacias[d] = "FF7030A0"
    r = anual.aprender_rotacion(fila, OCTUBRE)
    assert (r.patron, r.ancla) == ("6x3", date(2026, 10, 1))


def test_fila_entera_de_color_se_lee_como_libre():
    fila = _fila("BHS", "HIPODROMO", 0)
    for d in OCTUBRE:
        if d not in fila.jornadas:
            fila.marcas_vacias[d] = "FF7030A0"     # fondo de la fila, no una baja
    assert anual.aprender_rotacion(fila, OCTUBRE).patron == "6x3"


def test_partido_irregular_no_tiene_rotacion():
    fila = FilaCuadrante("PCP", "PARCIAL", 0)
    for d in OCTUBRE[::4]:
        fila.jornadas[d] = Jornada([(300, 480)])
    r = anual.aprender_rotacion(fila, OCTUBRE)
    assert r.patron == "irregular" and r.dia(date(2027, 3, 1)) == "?"
