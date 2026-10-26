"""Comprobaciones sobre la parrilla generada, con los mismos códigos que PARRITRON cuando existen."""
from __future__ import annotations

from datetime import date, timedelta

from .modelos import Equipo, Incidencia, Tarea, hhmm

DIAS_AVISO_CADUCIDAD = 30


def validar(equipos: list[Equipo], jardineras: list[Equipo], tareas: list[Tarea], tareas_jar: list[Tarea],
            asignadas: dict[str, str], transito: int, transito_jar: int, dia: date) -> list[Incidencia]:
    incidencias = []
    recursos = {r.codigo: r for r in equipos + jardineras}

    for t in tareas + tareas_jar:
        if t.id not in asignadas:
            codigo = "VUELO_SIN_EQUIPO" if t in tareas else "VUELO_SIN_JARDINERA"
            incidencias.append(Incidencia("PENDIENTE", codigo,
                                          f"{t.vuelo.codigo} ({t.tipo.lower()} {hhmm(t.inicio)}-{hhmm(t.fin)}) "
                                          "no cabe en ningún turno o recurso.", t.vuelo.fila_origen))
            continue
        r = recursos[asignadas[t.id]]
        if not (r.inicio <= t.inicio and t.fin <= r.fin):
            incidencias.append(Incidencia("PENDIENTE", "TRAMO_FUERA_TURNO",
                                          f"{t.vuelo.codigo} queda fuera del turno de {r.codigo}.", r.codigo))

    por_recurso: dict[str, list[Tarea]] = {}
    for t in tareas + tareas_jar:
        if t.id in asignadas:
            por_recurso.setdefault(asignadas[t.id], []).append(t)
    for codigo, lista in por_recurso.items():
        lista.sort(key=lambda t: t.inicio)
        margen = transito if recursos[codigo].seccion == "GRUPOS" else transito_jar
        for a, b in zip(lista, lista[1:]):
            if b.inicio < a.fin + margen:
                incidencias.append(Incidencia("PENDIENTE", "VUELOS_SOLAPADOS",
                                              f"{codigo}: {a.vuelo.codigo} y {b.vuelo.codigo} se solapan.", codigo))

    vistos: dict[str, list[Equipo]] = {}
    for equipo in equipos + jardineras:
        for puesto, e in equipo.miembros.items():
            if e is None:
                if equipo.seccion == "GRUPOS":
                    gravedad = "PENDIENTE" if puesto in ("TL", "PB/TOW") else "AVISO"
                    incidencias.append(Incidencia(gravedad, "EQUIPO_INCOMPLETO",
                                                  f"{equipo.codigo}: puesto {puesto} vacío.", equipo.codigo))
                continue
            # Quien tiene turno partido puede estar en dos equipos si los horarios no se pisan.
            for otro in vistos.get(e.id, []):
                if otro.inicio < equipo.fin and equipo.inicio < otro.fin:
                    incidencias.append(Incidencia("PENDIENTE", "EMPLEADO_DUPLICADO",
                                                  f"{e.id} está en {otro.codigo} y en {equipo.codigo} a la vez.",
                                                  equipo.codigo))
            vistos.setdefault(e.id, []).append(equipo)
            if puesto == "TL" and not e.habilitado("TL", dia):
                incidencias.append(Incidencia("AVISO", "TL_NO_CUALIFICADO", f"{equipo.codigo}: {e.id} sin habilitación TL.",
                                              equipo.codigo))
            if puesto == "PB/TOW" and not e.habilitado("PB/TOW", dia):
                incidencias.append(Incidencia("AVISO", "PB_NO_CUALIFICADO",
                                              f"{equipo.codigo}: {e.id} sin habilitación PB/TOW.", equipo.codigo))
            for h in e.habilitaciones:
                if h.nombre == puesto and h.caducidad and h.caducidad <= dia + timedelta(days=DIAS_AVISO_CADUCIDAD):
                    incidencias.append(Incidencia("AVISO", "HABILITACION_PROXIMA_A_CADUCAR",
                                                  f"{e.id}: {puesto} caduca el {h.caducidad:%d/%m/%Y}.", equipo.codigo))

    for equipo in equipos:
        if equipo.codigo not in por_recurso:
            incidencias.append(Incidencia("AVISO", "EQUIPO_SIN_VUELOS",
                                          f"{equipo.codigo} no tiene vuelos asignados.", equipo.codigo))
    return incidencias
