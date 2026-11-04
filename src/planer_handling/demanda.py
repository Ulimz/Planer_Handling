"""Convierte cada vuelo en tareas con su ventana de trabajo."""
from __future__ import annotations

from .configuracion import Configuracion
from .modelos import Tarea, Vuelo
from .operativa import tareas_de


def tareas_plataforma(vuelos: list[Vuelo], conf: Configuracion) -> list[Tarea]:
    """Tareas del recurso principal (en Azul, el equipo que hace el vuelo)."""
    return tareas_de(conf.operativa.principal, vuelos)


def tareas_jardinera(vuelos: list[Vuelo], conf: Configuracion) -> list[Tarea]:
    """Tareas del resto de recursos (en Azul, las jardineras)."""
    op = conf.operativa
    return [t for r in op.recursos if r is not op.principal for t in tareas_de(r, vuelos)]


def pico_simultaneo(tareas: list[Tarea], transito: int = 0) -> int:
    """Máximo de tareas a la vez, contando el tránsito entre vuelos."""
    eventos = sorted([(t.inicio, 1) for t in tareas] + [(t.fin + transito, -1) for t in tareas],
                     key=lambda e: (e[0], e[1]))
    actual = pico = 0
    for _, cambio in eventos:
        actual += cambio
        pico = max(pico, actual)
    return pico
