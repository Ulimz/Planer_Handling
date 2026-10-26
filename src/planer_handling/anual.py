"""Calendario de rotaciones de un año entero.

Continúa el ciclo de cada persona desde donde va en los cuadrantes más recientes: la rotación
no se reinicia en enero. Solo dice qué días trabaja cada uno y si es de mañana o de tarde; las
horas exactas dependen de la programación de vuelos de cada mes (ver mensual.py).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from .importar.cuadrante import FilaCuadrante
from .importar.vuelos import clave
from .mensual import AJUSTE_MINIMO_ROTACION, MEDIODIA, ROTACIONES

DIAS_CONOCIDOS_MINIMOS = 21     # con menos días fiables no se puede saber en qué punto del ciclo va


@dataclass
class Rotacion:
    funcion: str
    nombre: str
    patron: str                    # "6x3", "4x4" o "irregular"
    ajuste: float                  # proporción de días de referencia que encajan con el patrón
    ancla: date | None = None      # día en que la persona está en la posición 0 del ciclo
    fases: dict[int, str] = field(default_factory=dict)   # posición del ciclo -> "M" / "T"

    def ciclo(self) -> tuple[int, int] | None:
        return ROTACIONES.get(self.patron)

    def dia(self, d: date) -> str:
        """"M" o "T" si trabaja ese día, "" si libra y "?" si es irregular."""
        ciclo = self.ciclo()
        if not ciclo or self.ancla is None:
            return "?"
        pos = (d - self.ancla).days % sum(ciclo)
        return self.fases.get(pos, "M") if pos < ciclo[0] else ""


def unir_cuadrantes(*meses: list[FilaCuadrante]) -> list[FilaCuadrante]:
    """Une varios meses por persona (por nombre). Gana la función del mes más reciente."""
    por_clave: dict[str, FilaCuadrante] = {}
    for filas in meses:
        for f in filas:
            unida = por_clave.setdefault(clave(f.nombre), FilaCuadrante(f.funcion, f.nombre, f.fila))
            unida.funcion = f.funcion or unida.funcion
            unida.jornadas.update(f.jornadas)
            unida.marcas_vacias.update(f.marcas_vacias)
    return list(por_clave.values())


def aprender_rotacion(fila: FilaCuadrante, dias: list[date]) -> Rotacion:
    mejor = Rotacion(fila.funcion, fila.nombre, "irregular", 0.0)
    # Un día sin horario pero con color puede ser una baja o permiso (no se sabe si le tocaba
    # trabajar: el ciclo sigue corriendo) o solo el color de fondo de la fila. Se prueban las dos
    # lecturas y se queda la que mejor encaja.
    for color_es_libre in (False, True):
        estado = []                         # 1 trabaja, 0 libra, None no se sabe
        for d in dias:
            j = fila.jornadas.get(d)
            estado.append(1 if j and j.tramos else 0 if color_es_libre or d not in fila.marcas_vacias else None)
        conocidos = [(i, e) for i, e in enumerate(estado) if e is not None]
        if len(conocidos) < DIAS_CONOCIDOS_MINIMOS or not any(e for _, e in conocidos):
            continue
        for patron, (on, off) in ROTACIONES.items():
            largo = on + off
            for desfase in range(largo):
                ajuste = sum(((i + desfase) % largo < on) == bool(e) for i, e in conocidos) / len(conocidos)
                if ajuste > mejor.ajuste:
                    mejor = Rotacion(fila.funcion, fila.nombre, patron, ajuste, dias[0] - timedelta(days=desfase))
    if mejor.ajuste < AJUSTE_MINIMO_ROTACION:
        mejor.patron, mejor.ancla = "irregular", None
        return mejor
    largo = sum(mejor.ciclo())
    por_pos: dict[int, Counter] = {}
    for d in dias:
        j = fila.jornadas.get(d)
        if j and j.tramos:
            pos = (d - mejor.ancla).days % largo
            por_pos.setdefault(pos, Counter())["M" if j.tramos[0][0] < MEDIODIA else "T"] += 1
    mejor.fases = {pos: c.most_common(1)[0][0] for pos, c in por_pos.items()}
    return mejor


def dias_del_anio(anio: int) -> list[date]:
    inicio = date(anio, 1, 1)
    return [inicio + timedelta(days=i) for i in range((date(anio + 1, 1, 1) - inicio).days)]


def rotaciones(filas: list[FilaCuadrante], dias_referencia: list[date]) -> list[Rotacion]:
    return [aprender_rotacion(f, dias_referencia) for f in filas]


def rotaciones_recientes(meses: list[tuple[list[FilaCuadrante], list[date]]]) -> list[Rotacion]:
    """Rotación de cada persona a partir de varios meses (del más antiguo al más reciente).
    Primero se prueba con todos los meses juntos; si alguien no encaja (cambió de grupo, o tiene
    un mes lleno de bajas), con el mes más reciente en que sí encaja."""
    unidos = unir_cuadrantes(*(filas for filas, _ in meses))
    todos_los_dias = sorted({d for _, dias in meses for d in dias})
    por_mes = [{clave(r.nombre): r for r in rotaciones(filas, dias)} for filas, dias in reversed(meses)]
    resultado = []
    for fila in unidos:
        r = aprender_rotacion(fila, todos_los_dias)
        if r.patron == "irregular":
            r = next((m[clave(fila.nombre)] for m in por_mes
                      if clave(fila.nombre) in m and m[clave(fila.nombre)].patron != "irregular"), r)
            r.funcion = fila.funcion
        resultado.append(r)
    return resultado
