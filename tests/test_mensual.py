from datetime import date

from planer_handling import mensual
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.modelos import Vuelo

OCTUBRE = mensual.dias_del_mes(2026, 10)


def _fila(funcion, nombre, desfase, manana=(300, 780), tarde=(900, 1380)):
    """Persona 6x3 (MMMTTT + 3 libres) que empieza el ciclo `desfase` días antes del 1 de octubre."""
    fila = FilaCuadrante(funcion, nombre, 0)
    for i, dia in enumerate(OCTUBRE):
        pos = (i + desfase) % 9
        if pos < 6:
            fila.jornadas[dia] = Jornada([manana if pos < 3 else tarde])
    return fila


def test_aprende_rotacion_fases_y_horas(conf):
    perfiles = mensual.aprender_perfiles([_fila("TL", "UNO", 2)], OCTUBRE, conf)
    p = perfiles[0]
    assert (p.patron, p.desfase) == ("6x3", 2)
    assert [p.fases[k] for k in range(6)] == ["M", "M", "M", "T", "T", "T"]
    assert p.duracion == 480 and p.inicio_habitual["M"] == 300
    # La rotación continúa en noviembre sin reiniciarse.
    assert [p.trabaja(date(2026, 11, d), OCTUBRE[0]) for d in (1, 2, 3, 4)] == [False, False, False, True]


def test_empareja_llegada_y_salida_sueltas_en_un_giro():
    dia = date(2026, 11, 3)
    vuelos = [Vuelo(dia, vuelo_in="FR1", origen="EIN", sta=600),
              Vuelo(dia, vuelo_out="FR2", destino="DUB", std=650),
              Vuelo(dia, vuelo_out="FR3", destino="STN", std=360)]
    resultado = mensual.emparejar_giros(vuelos)
    assert [(v.codigo, v.sta, v.std) for v in resultado] == [("FR3", None, 360), ("FR1/FR2", 600, 650)]


def test_planifica_horarios_que_cubren_los_vuelos(conf):
    filas = [_fila("TL", "TL1", 0), _fila("PB", "PB1", 0)] + [_fila("PCP", f"OP{i}", 0) for i in range(3)]
    perfiles = mensual.aprender_perfiles(filas, OCTUBRE, conf)
    dia = date(2026, 11, 6)                              # primera mañana del ciclo
    vuelos = {dia: [Vuelo(dia, vuelo_in="FR1", origen="STN", sta=8 * 60, vuelo_out="FR2", destino="STN", std=8 * 60 + 30)]}
    cm = mensual.planificar_mes(vuelos, perfiles, OCTUBRE[0], conf, segundos_por_dia=5)
    dp = cm.dias[0]
    assert len(dp.jornadas) == 5
    assert all(j.inicio < 12 * 60 for j in dp.jornadas)   # le toca mañana a todos
    assert all(dp.deficit(r) == 0 for r in ("TL", "PB/TOW", "Operario"))
