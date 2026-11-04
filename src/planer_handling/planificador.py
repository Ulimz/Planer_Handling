"""Genera la parrilla de un día: personal disponible, equipos y asignación de vuelos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import asignacion, rotaciones, validacion
from .configuracion import Configuracion
from .equipos import Reparto, repartir
from .modelos import Empleado, Equipo, Incidencia, Tarea, Vuelo
from .operativa import Recurso, tareas_de


@dataclass
class GrupoParrilla:
    """Un tipo de recurso del día (equipos, PB, jardineras, coordinadores…) con sus tareas."""
    recurso: Recurso
    tareas: list[Tarea]
    equipos: list[Equipo]


@dataclass
class Parrilla:
    dia: date
    vuelos: list[Vuelo]
    tareas: list[Tarea]                 # las del recurso principal
    tareas_jardinera: list[Tarea]       # las del resto de recursos
    reparto: Reparto
    asignadas: dict[str, str]
    incidencias: list[Incidencia] = field(default_factory=list)
    grupos: list[GrupoParrilla] = field(default_factory=list)


def asignar_grupos(grupos: list[GrupoParrilla], segundos: float, minimizar: bool = False) -> dict[str, str]:
    """Reparte las tareas de cada tipo de recurso entre sus recursos. Con `minimizar`, los recursos
    de varias personas usan los menos posibles y el resto queda de refuerzo."""
    asignadas: dict[str, str] = {}
    for g in grupos:
        r = g.recurso
        minimo = minimizar and not r.por_orden_de_codigo
        asignadas |= asignacion.asignar(g.tareas, g.equipos, r.transito, segundos, minimizar_recursos=minimo,
                                        simultaneos=r.simultaneos, max_tareas=r.max_vuelos_dia)
        if minimo:
            usados = set(asignadas.values())
            for equipo in g.equipos:
                if equipo.codigo not in usados:
                    equipo.seccion = "REFUERZO"
    return asignadas


def parrilla(dia: date, vuelos: list[Vuelo], grupos: list[GrupoParrilla], reparto: Reparto,
             asignadas: dict[str, str], incidencias: list[Incidencia]) -> Parrilla:
    principal = next((g for g in grupos if g.recurso.principal), grupos[0])
    resto = [t for g in grupos if g is not principal for t in g.tareas]
    incidencias = incidencias + validacion.validar_grupos(grupos, asignadas, dia)
    return Parrilla(dia, vuelos, principal.tareas, resto, reparto, asignadas, incidencias, grupos)


def generar_parrilla(dia: date, vuelos: list[Vuelo], plantilla: list[Empleado], conf: Configuracion,
                     incidencias_previas: list[Incidencia] | None = None, segundos: float = 30) -> Parrilla:
    op = conf.operativa
    tareas = {r.nombre: tareas_de(r, vuelos) for r in op.recursos}
    necesarios = {r.nombre: asignacion.dimensionar(tareas[r.nombre], conf.turnos_por_codigo(r.turnos), r.transito,
                                                   simultaneos=r.simultaneos)
                  for r in op.recursos}
    salidas = {t.codigo: sum(1 for v in vuelos if v.std is not None and t.inicio <= v.std < t.fin)
               for t in conf.turnos_de("hipodromo")}

    disponibles = rotaciones.disponibles(plantilla, dia, conf)
    reparto = repartir(disponibles, necesarios, salidas, conf, dia)
    grupos = [GrupoParrilla(r, tareas[r.nombre], reparto.por_recurso[r.nombre]) for r in op.recursos]
    asignadas = asignar_grupos(grupos, segundos)
    incidencias = list(incidencias_previas or []) + reparto.incidencias
    return parrilla(dia, vuelos, grupos, reparto, asignadas, incidencias)
