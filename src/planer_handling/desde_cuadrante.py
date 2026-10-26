"""Parrilla del día a partir del cuadrante real: cada persona trae su horario y el motor
forma los equipos con quienes coinciden en horario y asigna los vuelos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from . import asignacion, demanda, validacion
from .configuracion import Configuracion
from .equipos import Reparto
from .importar.cuadrante import FilaCuadrante
from .importar.vuelos import clave
from .modelos import Empleado, Equipo, Habilitacion, Incidencia, Vuelo, hhmm
from .planificador import Parrilla

if TYPE_CHECKING:
    from .mensual import Ausencia


@dataclass
class Tramo:
    """Una persona disponible en [inicio, fin). Quien tiene turno partido aporta dos tramos."""
    empleado: Empleado
    inicio: int
    fin: int
    marca: str = ""


def empleados_desde_cuadrante(filas: list[FilaCuadrante], conf: Configuracion) -> tuple[list[Empleado], list[Incidencia]]:
    funciones = conf.datos.get("funciones", {})
    empleados, incidencias, desconocidas = [], [], set()
    for n, fila in enumerate(filas, 1):
        regla = funciones.get(fila.funcion)
        if regla is None:
            if fila.funcion not in desconocidas:
                desconocidas.add(fila.funcion)
                incidencias.append(Incidencia("AVISO", "FUNCION_DESCONOCIDA",
                                              f"La función '{fila.funcion}' no está en config; se trata como Operario."))
            regla = {"categoria": "Operario", "habilitaciones": ["Operario"]}
        e = Empleado(id=f"C{n:03d}", categoria=regla["categoria"], contrato=fila.funcion,
                     habilitaciones=[Habilitacion(h) for h in regla["habilitaciones"]], nombre=fila.nombre)
        empleados.append(e)
    return empleados, incidencias


def tramos_del_dia(filas: list[FilaCuadrante], empleados: list[Empleado], dia: date,
                   marcas: dict | None = None) -> tuple[list[Tramo], list[Incidencia]]:
    """Tramos de quien trabaja ese día. Una celda con un color de ausencia (vacaciones, baja,
    permiso, formación, sanción) deja a la persona fuera aunque tenga horas escritas."""
    marcas = marcas or {}
    resultado, incidencias = [], []
    for fila, e in zip(filas, empleados):
        jornada = fila.jornadas.get(dia)
        if not jornada:
            continue
        marca = marcas.get(jornada.marca)
        if marca and not marca["disponible"]:
            incidencias.append(Incidencia("AVISO", "AUSENCIA", f"{e.id} ({fila.funcion}): {marca['motivo']}.", e.id))
            continue
        if jornada.marca and not marca:
            incidencias.append(Incidencia("AVISO", "MARCA_DESCONOCIDA",
                                          f"{e.id}: color {jornada.marca} sin significado en config; se cuenta como disponible.",
                                          e.id))
        resultado += [Tramo(e, i, f, jornada.marca) for i, f in jornada.tramos]
    return resultado, incidencias


def formar_equipos_por_horario(tramos: list[Tramo], puestos: list[str], solape_minimo: int,
                               dia: date) -> tuple[list[Equipo], list[Tramo]]:
    """Cada TL disponible abre un equipo con su horario; el resto de puestos se cubre con quien
    más coincide con ese horario (al menos `solape_minimo` minutos)."""
    libres = sorted(tramos, key=lambda t: (t.inicio, t.fin, t.empleado.id))
    jefes = [t for t in libres if t.empleado.categoria == "TL"]
    equipos = []
    for jefe in jefes:
        if jefe not in libres:
            continue
        libres.remove(jefe)
        inicio, fin = jefe.inicio, jefe.fin
        miembros: dict[str, Empleado | None] = {puestos[0]: jefe.empleado}
        for puesto in puestos[1:]:
            candidatos = [t for t in libres if t.empleado.categoria != "TL"   # cada TL abre su propio equipo
                          and t.empleado.habilitado(puesto, dia) and t.empleado.id != jefe.empleado.id
                          and min(fin, t.fin) - max(inicio, t.inicio) >= solape_minimo
                          and all(m is None or m.id != t.empleado.id for m in miembros.values())]
            if not candidatos:
                miembros[puesto] = None
                continue
            elegido = min(candidatos, key=lambda t: (
                -(min(fin, t.fin) - max(inicio, t.inicio)),        # más coincidencia de horario
                t.empleado.categoria != puesto,                     # su función principal
                len(t.empleado.habilitaciones),                     # reservar a los polivalentes
                t.empleado.id))
            libres.remove(elegido)
            miembros[puesto] = elegido.empleado
        turno = "M" if inicio < 12 * 60 else "T"
        equipos.append(Equipo("", turno, inicio, fin, "GRUPOS", miembros))
    equipos.sort(key=lambda e: (e.inicio, e.fin))
    contador = {"M": 0, "T": 0}
    for e in equipos:
        contador[e.turno] += 1
        e.codigo = f"{e.turno}{contador[e.turno]}"
    return equipos, libres


def generar_parrilla_cuadrante(dia: date, vuelos: list[Vuelo], filas: list[FilaCuadrante], conf: Configuracion,
                               incidencias_previas: list[Incidencia] | None = None, segundos: float = 30,
                               ausencias: list[Ausencia] | None = None) -> Parrilla:
    """`ausencias`: registro de bajas, vacaciones… además de los colores del cuadrante."""
    empleados, incidencias = empleados_desde_cuadrante(filas, conf)
    tramos, por_color = tramos_del_dia(filas, empleados, dia, conf.datos.get("marcas"))
    incidencias += por_color
    ausentes = {}
    for a in ausencias or []:
        if a.desde <= dia <= a.hasta:
            ausentes[clave(a.empleado)] = a.motivo
    if ausentes:
        avisados = set()
        for t in tramos:
            motivo = ausentes.get(clave(t.empleado.nombre)) or ausentes.get(clave(t.empleado.id))
            if motivo and t.empleado.id not in avisados:
                avisados.add(t.empleado.id)
                incidencias.append(Incidencia("AVISO", "AUSENCIA", f"{t.empleado.id} ({t.empleado.contrato}): {motivo}.",
                                              t.empleado.id))
        tramos = [t for t in tramos if t.empleado.id not in avisados]
    plataforma = [t for t in tramos if t.empleado.categoria in conf.equipo_plataforma]
    equipos, sobrantes = formar_equipos_por_horario(plataforma, conf.equipo_plataforma,
                                                    conf.datos.get("solape_minimo_equipo", 120), dia)

    reparto = Reparto(equipos=equipos)
    for n, t in enumerate((t for t in tramos if t.empleado.categoria == "Jardinero"), 1):
        reparto.jardineras.append(Equipo(f"J{n}", "", t.inicio, t.fin, "JARDINERAS", {"Conductor": t.empleado}))
    for seccion, categoria, destino in (("HIPODROMO", "Hipodromo", reparto.hipodromo),
                                         ("MANDOS", "Mando intermedio", reparto.mandos)):
        for t in (t for t in tramos if t.empleado.categoria == categoria):
            destino.append(Equipo(f"{hhmm(t.inicio)}-{hhmm(t.fin)}", "", t.inicio, t.fin, seccion,
                                  {t.empleado.contrato: t.empleado}))
    reparto.reserva = [t.empleado for t in sobrantes]
    if not reparto.mandos:
        incidencias.append(Incidencia("PENDIENTE", "SIN_MANDO", "Ningún RCO/ARCO en el cuadrante de este día."))

    tareas = demanda.tareas_plataforma(vuelos, conf)
    tareas_jar = demanda.tareas_jardinera(vuelos, conf)
    transito, transito_jar = conf.servicio["transito_entre_vuelos"], conf.jardineras["transito"]
    asignadas = asignacion.asignar(tareas, reparto.equipos, transito, segundos, minimizar_recursos=True)
    # Los equipos que no hacen falta quedan de refuerzo (retrasos, cambios de última hora).
    usados = set(asignadas.values())
    for equipo in reparto.equipos:
        if equipo.codigo not in usados:
            equipo.seccion = "REFUERZO"
    asignadas |= asignacion.asignar(tareas_jar, reparto.jardineras, transito_jar, segundos)

    incidencias = list(incidencias_previas or []) + incidencias
    incidencias += validacion.validar(reparto.equipos, reparto.jardineras, tareas, tareas_jar,
                                      asignadas, transito, transito_jar, dia)
    return Parrilla(dia, vuelos, tareas, tareas_jar, reparto, asignadas, incidencias)
