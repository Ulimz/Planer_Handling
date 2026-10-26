"""Genera la parrilla de un día: personal disponible, equipos y asignación de vuelos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import asignacion, demanda, rotaciones, validacion
from .configuracion import Configuracion
from .equipos import Reparto, repartir
from .modelos import Empleado, Incidencia, Tarea, Vuelo


@dataclass
class Parrilla:
    dia: date
    vuelos: list[Vuelo]
    tareas: list[Tarea]
    tareas_jardinera: list[Tarea]
    reparto: Reparto
    asignadas: dict[str, str]
    incidencias: list[Incidencia] = field(default_factory=list)


def generar_parrilla(dia: date, vuelos: list[Vuelo], plantilla: list[Empleado], conf: Configuracion,
                     incidencias_previas: list[Incidencia] | None = None, segundos: float = 30) -> Parrilla:
    tareas = demanda.tareas_plataforma(vuelos, conf)
    tareas_jar = demanda.tareas_jardinera(vuelos, conf)
    transito = conf.servicio["transito_entre_vuelos"]
    transito_jar = conf.jardineras["transito"]

    necesarios = asignacion.dimensionar(tareas, conf.turnos_de("plataforma"), transito)
    necesarios_jar = asignacion.dimensionar(tareas_jar, conf.turnos_de("jardineras"), transito_jar)
    salidas = {t.codigo: sum(1 for v in vuelos if v.std is not None and t.inicio <= v.std < t.fin)
               for t in conf.turnos_de("hipodromo")}

    disponibles = rotaciones.disponibles(plantilla, dia, conf)
    reparto = repartir(disponibles, necesarios, necesarios_jar, salidas, conf, dia)

    asignadas = asignacion.asignar(tareas, reparto.equipos, transito, segundos)
    asignadas |= asignacion.asignar(tareas_jar, reparto.jardineras, transito_jar, segundos)

    incidencias = list(incidencias_previas or []) + reparto.incidencias
    incidencias += validacion.validar(reparto.equipos, reparto.jardineras, tareas, tareas_jar,
                                      asignadas, transito, transito_jar, dia)
    return Parrilla(dia, vuelos, tareas, tareas_jar, reparto, asignadas, incidencias)
