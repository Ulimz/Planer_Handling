from datetime import date

import pytest

from planer_handling import mensual
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.modelos import Vuelo
from planer_handling.registro import Almacen, motivos

from .test_mensual import OCTUBRE, _fila


def test_baja_abierta_y_alta(tmp_path, conf):
    almacen = Almacen(tmp_path)
    r = almacen.anadir("PEREZ, ANA", "PCP", "Baja por enfermedad común", date(2026, 11, 3))
    assert almacen.registros()[0].abierta and almacen.registros()[0].activa(date(2027, 1, 1))
    with pytest.raises(ValueError, match="ya tiene apuntado"):
        almacen.anadir("PEREZ, ANA", "PCP", "Vacaciones", date(2026, 12, 1), date(2026, 12, 5))
    almacen.dar_alta(r.id, date(2026, 11, 10))
    almacen.anadir("PEREZ, ANA", "PCP", "Vacaciones", date(2026, 12, 1), date(2026, 12, 5))
    registro = almacen.registros()[0]
    assert registro.hasta == date(2026, 11, 9) and not registro.activa(date(2026, 11, 10))
    assert motivos(conf)["Permiso de paternidad o maternidad"] == "FF00B0F0"
    assert motivos(conf)["Sanción disciplinaria"] == "FF000000"
    almacen.borrar(r.id)
    assert [x.motivo for x in almacen.registros()] == ["Vacaciones"]


def test_reorganizar_cubre_a_quien_falta_moviendo_lo_minimo(conf):
    # Dos TL de mañana y uno de tarde con su equipo; el de mañana TL1 se pone de baja el 6 de octubre.
    filas = [_fila("TL", "TL1", 0), _fila("TL", "TL2", 0, manana=(300, 780)), _fila("PB", "PB1", 0),
             _fila("PB", "PB2", 0)] + [_fila("PCP", f"OP{i}", 0) for i in range(6)]
    tarde = FilaCuadrante("TL", "TL_LIBRE", 0)       # no trabaja nunca de mañana el día 6
    for dia in OCTUBRE:
        if dia.day not in (5, 6, 7):
            tarde.jornadas[dia] = Jornada([(300, 780)])
    filas.append(tarde)
    dia = date(2026, 10, 1)                           # primera mañana del ciclo
    vuelos = {dia: [Vuelo(dia, vuelo_in="FR1", origen="STN", sta=8 * 60, vuelo_out="FR2", destino="STN", std=8 * 60 + 30),
                    Vuelo(dia, vuelo_in="FR3", origen="DUB", sta=8 * 60, vuelo_out="FR4", destino="DUB", std=8 * 60 + 30)]}
    ausencias = [mensual.Ausencia("TL1", dia, dia, "Baja laboral")]
    cm, cambios = mensual.reorganizar(filas, OCTUBRE, vuelos, ausencias, conf, 5)
    assert ("TL1", "Ausencia") in {(c.empleado, c.tipo) for c in cambios}
    assert all(c.empleado != "TL2" for c in cambios)             # quien ya cubría no se toca
    assert len(cm.dias) == len(OCTUBRE)


@pytest.mark.parametrize("contrato, dias_aviso, esperado", [
    ("TP", 0, None),                                   # sin preaviso y sin complementarias especiales
    ("TP", 2, None),
    ("TP", 5, "Complementarias pactadas (art. 18.5.5)"),
    ("TC", 0, "Perentorias (art. 36)"),
    ("TCC", 5, None),                                  # concreción horaria: no se le llama
])
def test_reorganizar_segun_contrato_y_preaviso(conf, contrato, dias_aviso, esperado):
    # TL1 se pone de baja la mañana del 1 de octubre; TL_L libra ese día y es el único que puede cubrirle.
    filas = [_fila("TL", "TL1", 0), _fila("TL", "TL_T", 3), _fila("TL", "TL_L", 6), _fila("PB", "PB1", 0)] + [
        _fila("PCP", f"OP{i}", 0) for i in range(3)]
    dia = date(2026, 10, 1)
    vuelos = {dia: [Vuelo(dia, vuelo_in="FR1", origen="STN", sta=8 * 60, vuelo_out="FR2", destino="STN", std=8 * 60 + 30)]}
    _, cambios = mensual.reorganizar(filas, OCTUBRE, vuelos, [mensual.Ausencia("TL1", dia, dia, "Baja laboral")], conf, 5,
                                     contratos={"TL_L": contrato}, aviso=date.fromordinal(dia.toordinal() - dias_aviso))
    llamadas = [c for c in cambios if c.empleado == "TL_L"]
    if esperado is None:
        assert not llamadas
    else:
        assert [(c.tipo, c.tipo_horas, c.preaviso) for c in llamadas] == [("Llamado en día libre", esperado, dias_aviso)]


def test_complementarias_especiales_si_la_empresa_las_tiene(conf):
    conf.datos["cambios_publicado"]["complementarias_especiales"] = True
    test_reorganizar_segun_contrato_y_preaviso(conf, "TP", 0, "Complementarias especiales (art. 19), voluntarias en día libre")


def test_tiempo_completo_sin_5_dias_de_preaviso_no_se_mueve(conf):
    p = mensual.aprender_perfiles([_fila("TL", "TC1", 0)], OCTUBRE, conf, {"TC1": "TC"})[0]
    assert mensual.reglas_cambio(p, 4, 0, conf)[0][0] is None
    assert mensual.reglas_cambio(p, 5, 0, conf)[0][0] is not None
    assert mensual.reglas_cambio(p, 0, 0, conf)[0][1] is not None      # llamarle: perentorias
