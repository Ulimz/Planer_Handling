"""Otra forma de trabajar en plataforma: grupos con capataz, PB aparte y coordinador de vuelos
(perfil config/ejemplo_grupos_capataz.yaml)."""
from datetime import date

import pandas as pd
import pytest

from planer_handling import mensual
from planer_handling.configuracion import Configuracion
from planer_handling.desde_cuadrante import generar_parrilla_cuadrante
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada
from planer_handling.modelos import Empleado, Habilitacion, Vuelo
from planer_handling.operativa import tareas_de
from planer_handling.parrilla_excel import exportar
from planer_handling.planificador import generar_parrilla

from .conftest import RAIZ

DIA = date(2027, 7, 12)
OCTUBRE = mensual.dias_del_mes(2026, 10)


@pytest.fixture
def otra() -> Configuracion:
    return Configuracion.cargar(RAIZ / "config" / "ejemplo_grupos_capataz.yaml")


def _persona(n: int, categoria: str, *habilitaciones: str) -> Empleado:
    return Empleado(f"E{n:03d}", categoria, "Fijo tiempo completo", rotacion="",
                    habilitaciones=[Habilitacion(h) for h in (categoria, *habilitaciones)])


def _plantilla() -> list[Empleado]:
    personas, n = [], 0
    for categoria, cuantos, extra in (("Capataz", 6, ["Operario"]), ("TRT", 6, ["Operario"]),
                                      ("Operario", 24, []), ("PB/TOW", 6, ["Operario"]),
                                      ("Coordinador", 3, []), ("Jardinero", 2, [])):
        for _ in range(cuantos):
            n += 1
            personas.append(_persona(n, categoria, *extra))
    return personas


def _vuelos() -> list[Vuelo]:
    # Seis giros de mañana, uno en remoto, y una salida sola.
    vuelos = [Vuelo(DIA, f"XX{100 + i}", "MAN", 360 + 40 * i, f"XX{200 + i}", "MAN", 360 + 40 * i + 35,
                    puesto="REMOTO" if i == 2 else "CONTACTO") for i in range(6)]
    return vuelos + [Vuelo(DIA, vuelo_out="XX300", destino="EDI", std=420, puesto="CONTACTO")]


def test_la_operativa_se_lee_del_perfil(otra, conf):
    op = otra.operativa
    assert [r.nombre for r in op.recursos] == ["Pushback", "Coordinador", "Grupo", "Jardinera"]
    assert op.principal.nombre == "Grupo"
    assert op.principal.etiquetas() == ["Capataz", "TRT", "Operario 1", "Operario 2", "Operario 3"]
    assert op.categorias() == ["PB/TOW", "Coordinador", "Capataz", "TRT", "Operario"]
    # El perfil de Azul, que no tiene `operativa`, sigue con su equipo completo y sus jardineras.
    azul = conf.operativa
    assert [r.nombre for r in azul.recursos] == ["Equipo", "Jardinera"]
    assert azul.principal.personas_por_categoria() == {"TL": 1, "PB/TOW": 1, "Operario": 3}


def test_tareas_de_cada_recurso(otra):
    op = {r.nombre: r for r in otra.operativa.recursos}
    vuelos = _vuelos()
    pb = tareas_de(op["Pushback"], vuelos)
    assert len(pb) == 7 and all(t.tipo == "SALIDA" for t in pb)          # una por cada salida
    assert (pb[0].inicio, pb[0].fin) == (395 - 10, 395 + 5)                # 10 min antes del STD
    grupo = tareas_de(op["Grupo"], vuelos)
    assert sorted(t.tipo for t in grupo) == ["GIRO"] * 6 + ["SALIDA"]
    assert len(tareas_de(op["Jardinera"], vuelos)) == 2                    # el giro en remoto


def test_parrilla_con_grupos_pb_y_coordinadores(otra, tmp_path):
    p = generar_parrilla(DIA, _vuelos(), _plantilla(), otra, segundos=5)
    nombres = [g.recurso.nombre for g in p.grupos]
    assert nombres == ["Pushback", "Coordinador", "Grupo", "Jardinera"]
    por = {g.recurso.nombre: g for g in p.grupos}
    # Todas las tareas tienen recurso y nadie está en dos sitios a la vez.
    assert all(t.id in p.asignadas for g in p.grupos for t in g.tareas)
    codigos = {i.codigo for i in p.incidencias}
    assert not codigos & {"EMPLEADO_DUPLICADO", "VUELOS_SOLAPADOS", "TRAMO_FUERA_TURNO", "DEMASIADOS_VUELOS"}
    # Los grupos son de 5 con capataz; los PB van sueltos y cada uno lo lleva un PB.
    grupo = por["Grupo"].equipos[0]
    assert list(grupo.miembros) == ["Capataz", "TRT", "Operario 1", "Operario 2", "Operario 3"]
    assert grupo.miembros["Capataz"].categoria == "Capataz"
    assert all(e.miembros["PB/TOW"].categoria == "PB/TOW" for e in por["Pushback"].equipos)
    assert p.reparto.equipos == por["Grupo"].equipos
    # Un coordinador lleva hasta 3 vuelos a la vez: con 3 en el aire basta uno.
    coordinadores = {p.asignadas[t.id] for t in por["Coordinador"].tareas}
    assert len(coordinadores) == 1
    hojas = pd.read_excel(exportar(p, tmp_path / "parrilla.xlsx", otra.equipo_plataforma), sheet_name=None)
    assert {"Grupos", "Pushback", "Coordinador", "Jardinera"} <= set(hojas)
    assert "Operario 3" in hojas["Grupos"].columns


def test_coordinador_no_pasa_de_sus_vuelos_del_dia(otra):
    otra.datos["operativa"]["recursos"]["Coordinador"]["max_vuelos_dia"] = 2
    p = generar_parrilla(DIA, _vuelos(), _plantilla(), otra, segundos=5)
    coord = next(g for g in p.grupos if g.recurso.nombre == "Coordinador")
    por_coordinador = {}
    for t in coord.tareas:
        if t.id in p.asignadas:
            por_coordinador.setdefault(p.asignadas[t.id], []).append(t)
    assert por_coordinador and all(len(v) <= 2 for v in por_coordinador.values())
    # Con 3 coordinadores de 2 vuelos no llegan para 7 vuelos: se avisa de los que quedan sin coordinador.
    assert "VUELO_SIN_COORDINADOR" in {i.codigo for i in p.incidencias}


def test_demanda_del_mes_por_categoria(otra):
    demanda = mensual.demanda_del_dia(_vuelos(), otra)
    assert set(demanda) == {"PB/TOW", "Coordinador", "Capataz", "TRT", "Operario", "Pasaje", "Responsable pasaje"}
    assert "TL" not in demanda
    # Cada grupo a la vez pide 1 capataz, 1 TRT y 3 operarios.
    assert max(demanda["Operario"]) == 3 * max(demanda["Capataz"])
    assert max(demanda["TRT"]) == max(demanda["Capataz"])
    # Tres vuelos a la vez los lleva un solo coordinador.
    assert max(demanda["Coordinador"]) == 1


def _fila(funcion: str, nombre: str) -> FilaCuadrante:
    fila = FilaCuadrante(funcion, nombre, 0)
    for i, dia in enumerate(OCTUBRE):
        if (i % 9) < 6:
            fila.jornadas[dia] = Jornada([(300, 780)])
    return fila


def test_cuadrante_del_mes_cubre_capataz_trt_pb_y_coordinador(otra):
    filas = ([_fila("CAP", "CAP1"), _fila("TRT", "TRT1"), _fila("PB", "PB1"), _fila("COORD", "CO1")]
             + [_fila("OPE", f"OP{i}") for i in range(3)])
    perfiles = mensual.aprender_perfiles(filas, OCTUBRE, otra)
    dia = date(2026, 11, 6)                              # primer día de trabajo del ciclo en noviembre
    vuelos = {dia: [Vuelo(dia, "XX1", "STN", 8 * 60, "XX2", "STN", 8 * 60 + 30)]}
    cm = mensual.planificar_mes(vuelos, perfiles, OCTUBRE[0], otra, segundos_por_dia=5)
    dp = cm.dias[0]
    assert len(dp.jornadas) == 7
    assert all(dp.deficit(r) == 0 for r in ("Capataz", "TRT", "PB/TOW", "Coordinador", "Operario"))


def test_parrilla_desde_cuadrante_con_otra_operativa(otra):
    filas = ([_fila("CAP", "CAP1"), _fila("TRT", "TRT1"), _fila("PB", "PB1"), _fila("COORD", "CO1")]
             + [_fila("OPE", f"OP{i}") for i in range(3)])
    dia = OCTUBRE[0]
    vuelos = [Vuelo(dia, "XX1", "STN", 8 * 60, "XX2", "STN", 8 * 60 + 30)]
    p = generar_parrilla_cuadrante(dia, vuelos, filas, otra, segundos=5)
    por = {g.recurso.nombre: g for g in p.grupos}
    assert len(por["Grupo"].equipos) == 1 and por["Grupo"].equipos[0].completo
    assert len(por["Pushback"].equipos) == 1 and len(por["Coordinador"].equipos) == 1
    assert all(t.id in p.asignadas for g in p.grupos for t in g.tareas)
    assert "SIN_MANDO" not in {i.codigo for i in p.incidencias}
