"""Ficha de plantilla: aprender de los cuadrantes y planificar sin turnos previos."""
from datetime import date, timedelta

from planer_handling import plantilla
from planer_handling.archivo import Archivo
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.mensual import dias_del_mes, planificar_mes
from planer_handling.modelos import Vuelo


def _fila(conf, codigo, funcion, grupo, dias, rotacion="6x3", m=285, t=1080, horas=8):
    regla = conf.datos["rotaciones"][rotacion]
    ciclo = regla["trabajo"] + regla["libre"]
    desfase = regla["grupos"][grupo]
    f = FilaCuadrante(funcion, codigo, 1)
    for d in dias:
        pos = ((d - conf.inicio_ciclos).days + desfase) % ciclo
        if pos < regla["trabajo"]:
            inicio = m if regla["fases"][pos] == "M" else t
            f.jornadas[d] = Jornada([(inicio, inicio + horas * 60)])
    return f


def test_aprende_grupo_fases_y_entrada(conf):
    meses = []
    for mes in (9, 10):
        dias = dias_del_mes(2026, mes)
        filas = [_fila(conf, "P0001", "TL", "1", dias), _fila(conf, "P0002", "PCP", "3", dias, m=300, t=1020, horas=5),
                 _fila(conf, "P0003", "RCO", "2", dias, rotacion="4x4", m=315, t=900, horas=10)]
        meses.append((filas, dias))
    ficha, resumen = plantilla.aprender(meses, conf, {"P0002": "TP"})
    por = {p.codigo: p for p in ficha}
    assert (por["P0001"].rotacion, por["P0001"].grupo, por["P0001"].fases) == ("6x3", "1", "")
    assert (por["P0002"].grupo, por["P0002"].habitual, por["P0002"].contrato) == ("3", "05:00/17:00", "TP")
    assert (por["P0003"].rotacion, por["P0003"].grupo) == ("4x4", "2")
    assert resumen["encaje_medio"] == 1


def test_ficha_en_tabla_ida_y_vuelta():
    p = plantilla.Persona("P0001", "PCP", "TP", "6x3", "2", "", 1200, "04:45/18:00", "", "3+3")
    vuelta, errores = plantilla.desde_tabla(plantilla.tabla([p]))
    assert vuelta == [p] and not errores
    _, errores = plantilla.desde_tabla([{"Código": "P1", "Turnos del ciclo": "MXT", "Partido": "a"}])
    assert len(errores) == 2


def test_planifica_noviembre_solo_con_la_ficha(conf, tmp_path):
    ficha = [plantilla.Persona(f"P{i:04d}", "TL", "TC", "6x3", g) for i, g in enumerate("123123", 1)]
    ficha += [plantilla.Persona(f"P{i:04d}", "PCP", "TC", "6x3", g) for i, g in enumerate("123123123123123123", 7)]
    ficha += [plantilla.Persona("P0099", "PCP", "TP", "6x3", "1", horas_anuales=40)]
    dias = dias_del_mes(2026, 11)[:9]
    vuelos = {d: [Vuelo(d, "XX1", "MAD", 600, "XX2", "MAD", 640, "B738")] for d in dias}
    perfiles, avisos = plantilla.perfiles(ficha, conf, 2026, 11)
    assert not avisos
    cm = planificar_mes(vuelos, perfiles, date(2026, 11, 1), conf, 1)
    p1 = next(p for p in perfiles if p.empleado.id == "P0001")
    trabaja = [any(j.perfil is p1 for j in d.jornadas) for d in cm.dias]
    assert sum(trabaja) == 6                      # 6 de cada 9 días, sin turnos de nadie
    # El parcial no pasa del tope del mes (40 h al año repartidas en lo que queda de año).
    parcial = sum(j.minutos for d in cm.dias for j in d.jornadas if j.perfil.empleado.id == "P0099")
    assert parcial <= next(p for p in perfiles if p.empleado.id == "P0099").minutos_objetivo


def test_cuenta_anual(conf, tmp_path):
    arch = Archivo(tmp_path)
    dias = dias_del_mes(2026, 1)
    arch.guardar_cuadrante(2026, 1, [_fila(conf, "P0001", "TL", "1", dias)])
    p = plantilla.Persona("P0001", "TL", "TC", "6x3", "1")
    fila = plantilla.cuenta_anual([p], arch, conf, 2026, 2, {"P0001": 100})[0]
    assert fila["Horas al año"] == 1712 and fila["Hechas antes"] > 100
    assert fila["Quedan para el resto del año"] == round(1712 - fila["Hechas antes"] - 100, 1)
