"""Asignación de tareas a recursos (equipos o conductores) con OR-Tools CP-SAT."""
from __future__ import annotations

from ortools.sat.python import cp_model

from .modelos import Tarea

PENALIZACION_SIN_ASIGNAR = 1000


def dimensionar(tareas: list[Tarea], turnos, transito: int, paso: int = 15) -> dict[str, int]:
    """Mínimo número de recursos por turno. Cada tarea se reparte a un turno que la contenga entera
    y, en cada franja de `paso` minutos, cada turno necesita tantos recursos como tareas suyas
    coinciden en ella. Las tareas que no caben en ningún turno se ignoran aquí (las señala la validación)."""
    if not tareas:
        return {t.codigo: 0 for t in turnos}
    modelo = cp_model.CpModel()
    n = {t.codigo: modelo.NewIntVar(0, len(tareas), t.codigo) for t in turnos}
    eleccion: dict[tuple[str, str], cp_model.IntVar] = {}
    for tarea in tareas:
        opciones = []
        for t in turnos:
            if t.inicio <= tarea.inicio and tarea.fin <= t.fin:
                var = modelo.NewBoolVar(f"y_{tarea.id}_{t.codigo}")
                eleccion[tarea.id, t.codigo] = var
                opciones.append(var)
        if opciones:
            modelo.AddExactlyOne(opciones)
    inicio = min(t.inicio for t in tareas) // paso * paso
    fin = max(t.fin + transito for t in tareas)
    for franja in range(inicio, fin, paso):
        activas = [t for t in tareas if t.inicio < franja + paso and franja < t.fin + transito]
        for t in turnos:
            suyas = [eleccion[a.id, t.codigo] for a in activas if (a.id, t.codigo) in eleccion]
            if suyas:
                modelo.Add(n[t.codigo] >= sum(suyas))
    modelo.Minimize(sum(n.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    solver.parameters.num_workers = 8
    if solver.Solve(modelo) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("No se pudo dimensionar la plantilla por turnos.")
    return {codigo: solver.Value(v) for codigo, v in n.items()}


def asignar(tareas: list[Tarea], recursos: list, transito: int, segundos: float = 30) -> dict[str, str]:
    """Devuelve {id_tarea: codigo_recurso}. Las tareas que no caben quedan fuera del resultado.

    Cada recurso necesita `inicio`, `fin` y `codigo`. Un recurso no puede tener dos tareas
    a la vez y entre una tarea y la siguiente deja `transito` minutos.
    """
    modelo = cp_model.CpModel()
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    intervalos: dict[str, list] = {r.codigo: [] for r in recursos}
    for t in tareas:
        for r in recursos:
            if r.inicio <= t.inicio and t.fin <= r.fin:
                var = modelo.NewBoolVar(f"x_{t.id}_{r.codigo}")
                x[t.id, r.codigo] = var
                intervalos[r.codigo].append(
                    modelo.NewOptionalFixedSizeIntervalVar(t.inicio, t.fin - t.inicio + transito, var, f"i_{t.id}_{r.codigo}")
                )

    sin_asignar = []
    for t in tareas:
        opciones = [v for (tid, _), v in x.items() if tid == t.id]
        modelo.Add(sum(opciones) <= 1)
        sin_asignar.append(1 - sum(opciones))
    for lista in intervalos.values():
        modelo.AddNoOverlap(lista)

    # Repartir la carga: minimizar los minutos del recurso más cargado.
    carga_max = modelo.NewIntVar(0, 2 * 1440, "carga_max")
    for r in recursos:
        modelo.Add(sum((t.fin - t.inicio) * x[t.id, r.codigo] for t in tareas if (t.id, r.codigo) in x) <= carga_max)

    modelo.Minimize(PENALIZACION_SIN_ASIGNAR * sum(sin_asignar) + carga_max)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = segundos
    solver.parameters.num_workers = 8
    estado = solver.Solve(modelo)
    if estado not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("El optimizador no encontró una asignación válida.")
    return {tid: rcod for (tid, rcod), var in x.items() if solver.Value(var)}
