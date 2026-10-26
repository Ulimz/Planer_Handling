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


def test_partidos_y_ausencias(conf, tmp_path):
    import pandas as pd
    from planer_handling.importar.ausencias import leer_ausencias
    partida = _fila("PCP", "PARTIDO", 0)
    for jornada in partida.jornadas.values():
        jornada.tramos = [(300, 420), (600, 720)]           # 05:00-07:00 y 10:00-12:00
    filas = [_fila("TL", "TL1", 0), _fila("PB", "PB1", 0), partida, _fila("PCP", "VACACIONES", 0)]
    perfiles = mensual.aprender_perfiles(filas, OCTUBRE, conf)
    assert perfiles[2].partido == (120, 180, 120)
    ruta = tmp_path / "ausencias.xlsx"
    pd.DataFrame({"Empleado": ["VACACIONES"], "Desde": ["01/11/2026"], "Hasta": ["15/11/2026"],
                  "Motivo": ["Vacaciones"]}).to_excel(ruta, index=False)
    dia = date(2026, 11, 6)
    # Dos giros separados: a las 06:00 y a las 11:00. Un partido los cubre mejor que un bloque.
    vuelos = {dia: [Vuelo(dia, vuelo_in="FR1", origen="STN", sta=6 * 60, vuelo_out="FR2", destino="STN", std=6 * 60 + 30),
                    Vuelo(dia, vuelo_in="FR3", origen="DUB", sta=11 * 60, vuelo_out="FR4", destino="DUB", std=11 * 60 + 30)]}
    cm = mensual.planificar_mes(vuelos, perfiles, OCTUBRE[0], conf, 5, leer_ausencias(ruta))
    dp = cm.dias[0]
    assert dp.ausentes == {perfiles[3].empleado.id: "Vacaciones"}
    assert {j.perfil.empleado.nombre for j in dp.jornadas} == {"TL1", "PB1", "PARTIDO"}
    assert len(next(j for j in dp.jornadas if j.perfil.empleado.nombre == "PARTIDO").tramos) == 2
    assert mensual.texto_jornada([(300, 420), (600, 720)]) == "05:00\n07:00\n\n10:00\n12:00"
