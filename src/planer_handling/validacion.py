"""Comprobaciones sobre la parrilla generada, con los mismos códigos que PARRITRON cuando existen."""
from __future__ import annotations

from datetime import date, timedelta

from .modelos import Equipo, Incidencia, Tarea, hhmm

DIAS_AVISO_CADUCIDAD = 30


def validar_grupos(grupos, asignadas: dict[str, str], dia: date) -> list[Incidencia]:
    """`grupos`: cada tipo de recurso con sus tareas y sus equipos (ver `planificador.GrupoParrilla`)."""
    incidencias = []
    recursos = {e.codigo: e for g in grupos for e in g.equipos}
    grupo_de = {e.codigo: g for g in grupos for e in g.equipos}

    for g in grupos:
        for t in g.tareas:
            if t.id not in asignadas:
                incidencias.append(Incidencia("PENDIENTE", f"VUELO_SIN_{g.recurso.nombre.upper()}",
                                              f"{t.vuelo.codigo} ({t.tipo.lower()} {hhmm(t.inicio)}-{hhmm(t.fin)}) "
                                              "no cabe en ningún turno o recurso.", t.vuelo.fila_origen))
                continue
            r = recursos[asignadas[t.id]]
            if not (r.inicio <= t.inicio and t.fin <= r.fin):
                incidencias.append(Incidencia("PENDIENTE", "TRAMO_FUERA_TURNO",
                                              f"{t.vuelo.codigo} queda fuera del turno de {r.codigo}.", r.codigo))

    por_recurso: dict[str, list[Tarea]] = {}
    for g in grupos:
        for t in g.tareas:
            if t.id in asignadas:
                por_recurso.setdefault(asignadas[t.id], []).append(t)
    for codigo, lista in por_recurso.items():
        lista.sort(key=lambda t: t.inicio)
        recurso = grupo_de[codigo].recurso
        margen = recurso.transito
        # Con varios vuelos a la vez (un coordinador), solo se avisa si pasa de los que puede llevar.
        for n, b in enumerate(lista):
            a_la_vez = [a for a in lista[:n] if b.inicio < a.fin + margen]
            if len(a_la_vez) >= recurso.simultaneos:
                a = a_la_vez[-1]
                incidencias.append(Incidencia("PENDIENTE", "VUELOS_SOLAPADOS",
                                              f"{codigo}: {a.vuelo.codigo} y {b.vuelo.codigo} se solapan.", codigo))
        if recurso.max_vuelos_dia is not None and len(lista) > recurso.max_vuelos_dia:
            incidencias.append(Incidencia("PENDIENTE", "DEMASIADOS_VUELOS",
                                          f"{codigo}: {len(lista)} vuelos, más de {recurso.max_vuelos_dia}.", codigo))

    vistos: dict[str, list[Equipo]] = {}
    for g in grupos:
        recurso = g.recurso
        etiqueta_a_puesto = dict(zip(recurso.etiquetas(), recurso.puestos))
        for equipo in g.equipos:
            for etiqueta, e in equipo.miembros.items():
                puesto = etiqueta_a_puesto.get(etiqueta, etiqueta)
                if e is None:
                    if equipo.seccion != "REFUERZO" and not recurso.por_orden_de_codigo:
                        gravedad = "PENDIENTE" if puesto in recurso.puestos_clave else "AVISO"
                        incidencias.append(Incidencia(gravedad, "EQUIPO_INCOMPLETO",
                                                      f"{equipo.codigo}: puesto {etiqueta} vacío.", equipo.codigo))
                    continue
                # Quien tiene turno partido puede estar en dos equipos si los horarios no se pisan.
                for otro in vistos.get(e.id, []):
                    if otro.inicio < equipo.fin and equipo.inicio < otro.fin:
                        incidencias.append(Incidencia("PENDIENTE", "EMPLEADO_DUPLICADO",
                                                      f"{e.id} está en {otro.codigo} y en {equipo.codigo} a la vez.",
                                                      equipo.codigo))
                vistos.setdefault(e.id, []).append(equipo)
                if puesto in recurso.puestos_clave and not e.habilitado(puesto, dia):
                    codigo = {"TL": "TL_NO_CUALIFICADO", "PB/TOW": "PB_NO_CUALIFICADO"}.get(puesto, "NO_CUALIFICADO")
                    incidencias.append(Incidencia("AVISO", codigo, f"{equipo.codigo}: {e.id} sin habilitación {puesto}.",
                                                  equipo.codigo))
                for h in e.habilitaciones:
                    if h.nombre == puesto and h.caducidad and h.caducidad <= dia + timedelta(days=DIAS_AVISO_CADUCIDAD):
                        incidencias.append(Incidencia("AVISO", "HABILITACION_PROXIMA_A_CADUCAR",
                                                      f"{e.id}: {puesto} caduca el {h.caducidad:%d/%m/%Y}.", equipo.codigo))

    for g in grupos:
        if g.recurso.por_orden_de_codigo:
            continue
        for equipo in g.equipos:
            if equipo.codigo not in por_recurso and equipo.seccion != "REFUERZO":
                incidencias.append(Incidencia("AVISO", f"{'EQUIPO' if g.recurso.principal else g.recurso.nombre.upper()}_SIN_VUELOS",
                                              f"{equipo.codigo} no tiene vuelos asignados.", equipo.codigo))
    return incidencias
