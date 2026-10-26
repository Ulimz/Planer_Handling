"""Convierte cada vuelo en tareas con su ventana de trabajo."""
from __future__ import annotations

from .configuracion import Configuracion
from .modelos import Tarea, Vuelo


def tareas_plataforma(vuelos: list[Vuelo], conf: Configuracion) -> list[Tarea]:
    s = conf.servicio
    tareas = []
    for i, v in enumerate(vuelos):
        if v.sta is not None and v.std is not None:
            tareas.append(Tarea(f"P{i:03d}", "GIRO", v.sta - s["giro"]["antes_sta"],
                                v.std + s["giro"]["despues_std"], v))
        elif v.std is not None:
            tareas.append(Tarea(f"P{i:03d}", "SALIDA", v.std - s["solo_salida"]["antes_std"],
                                v.std + s["solo_salida"]["despues_std"], v))
        elif v.sta is not None:
            tareas.append(Tarea(f"P{i:03d}", "LLEGADA", v.sta - s["solo_llegada"]["antes_sta"],
                                v.sta + s["solo_llegada"]["despues_sta"], v))
    return tareas


def tareas_jardinera(vuelos: list[Vuelo], conf: Configuracion) -> list[Tarea]:
    j = conf.jardineras
    tareas = []
    for i, v in enumerate(vuelos):
        if not v.remoto:
            continue
        if v.sta is not None:
            tareas.append(Tarea(f"J{i:03d}L", "JARDINERA_LLEGADA", v.sta + j["llegada"]["desde_sta"],
                                v.sta + j["llegada"]["hasta_sta"], v))
        if v.std is not None:
            tareas.append(Tarea(f"J{i:03d}S", "JARDINERA_SALIDA", v.std - j["salida"]["antes_std"],
                                v.std - j["salida"]["hasta_antes_std"], v))
    return tareas


def pico_simultaneo(tareas: list[Tarea], transito: int = 0) -> int:
    """Máximo de tareas a la vez, contando el tránsito entre vuelos."""
    eventos = sorted([(t.inicio, 1) for t in tareas] + [(t.fin + transito, -1) for t in tareas],
                     key=lambda e: (e[0], e[1]))
    actual = pico = 0
    for _, cambio in eventos:
        actual += cambio
        pico = max(pico, actual)
    return pico
