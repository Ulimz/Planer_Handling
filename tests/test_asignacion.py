from datetime import date

from planer_handling.asignacion import asignar, dimensionar
from planer_handling.configuracion import Turno
from planer_handling.modelos import Equipo, Tarea, Vuelo


def tarea(i, inicio, fin):
    return Tarea(f"T{i}", "GIRO", inicio, fin, Vuelo(date(2027, 7, 15), vuelo_out=f"FR{i}"))


def test_dimensionar_cubre_el_pico_de_cada_turno():
    tareas = [tarea(i, 360, 400) for i in range(3)] + [tarea(9, 900, 940)]
    turnos = [Turno("M", 270, 750), Turno("T", 750, 1230)]
    assert dimensionar(tareas, turnos, transito=10) == {"M": 3, "T": 1}


def test_asignar_sin_solapes_y_respetando_transito():
    tareas = [tarea(0, 360, 400), tarea(1, 405, 440), tarea(2, 420, 460)]
    equipos = [Equipo("M01", "M", 270, 750), Equipo("M02", "M", 270, 750)]
    resultado = asignar(tareas, equipos, transito=10)
    assert len(resultado) == 3
    # T0 y T1 no pueden ir juntas (solo 5 min entre ellas), así que T1 va con el otro equipo
    assert resultado["T0"] != resultado["T1"]
    assert resultado["T0"] == resultado["T2"]


def test_tarea_fuera_de_turno_queda_sin_asignar():
    tareas = [tarea(0, 200, 240)]
    assert asignar(tareas, [Equipo("M01", "M", 270, 750)], transito=10) == {}
