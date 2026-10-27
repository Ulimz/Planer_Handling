"""Formación de equipos de plataforma y reparto del resto de colectivos por turnos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .configuracion import Configuracion, Turno
from .modelos import Empleado, Equipo, Incidencia

CATEGORIAS_SIN_EQUIPO = {"Jardinero", "Hipodromo", "Mando intermedio"}


@dataclass
class Reparto:
    equipos: list[Equipo] = field(default_factory=list)
    jardineras: list[Equipo] = field(default_factory=list)
    hipodromo: list[Equipo] = field(default_factory=list)
    mandos: list[Equipo] = field(default_factory=list)
    parciales: list[Equipo] = field(default_factory=list)
    reserva: list[Empleado] = field(default_factory=list)
    incidencias: list[Incidencia] = field(default_factory=list)


def _habilitaciones_vigentes(e: Empleado, dia: date) -> int:
    return sum(1 for h in e.habilitaciones if h.vigente(dia))


def formar_equipos(personal: list[Empleado], necesarios: dict[str, int], turnos: dict[str, Turno],
                   puestos: list[str], dia: date) -> tuple[list[Equipo], list[Empleado], list[Incidencia]]:
    """Forma `necesarios[turno]` equipos por turno. Cada puesto se cubre con quien tenga la
    habilitación vigente, prefiriendo a quien la tiene como categoría principal y reservando
    a los más polivalentes para los puestos que queden."""
    # Se completan los equipos uno a uno, alternando turnos (M01, T01, N01, M02...), para que
    # si falta personal salgan menos equipos completos y no muchos equipos a medias.
    orden = []
    for n in range(1, max(necesarios.values(), default=0) + 1):
        for codigo, cantidad in necesarios.items():
            if n <= cantidad:
                t = turnos[codigo]
                orden.append(Equipo(f"{codigo}{n:02d}", codigo, t.inicio, t.fin, "GRUPOS", {p: None for p in puestos}))
    libres = list(personal)
    incidencias: list[Incidencia] = []
    for equipo in orden:
        for puesto in puestos:
            candidatos = [e for e in libres if e.habilitado(puesto, dia)]
            if not candidatos:
                continue  # queda VACANTE; la validación lo señala como EQUIPO_INCOMPLETO
            elegido = min(candidatos, key=lambda e: (e.categoria != puesto, _habilitaciones_vigentes(e, dia), e.id))
            equipo.miembros[puesto] = elegido
            libres.remove(elegido)
    equipos = sorted(orden, key=lambda e: (list(necesarios).index(e.turno), e.codigo))
    return equipos, libres, incidencias


def repartir(disponibles: list[Empleado], necesarios_plataforma: dict[str, int],
             necesarios_jardineras: dict[str, int], salidas_por_turno: dict[str, int],
             conf: Configuracion, dia: date) -> Reparto:
    turnos = conf.turnos
    reparto = Reparto()
    parciales = [e for e in disponibles if e.contrato == "Tiempo parcial"]
    completos = [e for e in disponibles if e not in parciales]

    plataforma = [e for e in completos if e.categoria not in CATEGORIAS_SIN_EQUIPO]
    reparto.equipos, sobrantes, inc = formar_equipos(plataforma, necesarios_plataforma, turnos,
                                                     conf.equipo_plataforma, dia)
    reparto.incidencias += inc
    reparto.reserva = sobrantes

    # Jardineras: un conductor por recurso.
    conductores = sorted((e for e in completos if e.categoria == "Jardinero"), key=lambda e: e.id)
    for codigo, cantidad in necesarios_jardineras.items():
        t = turnos[codigo]
        for n in range(1, cantidad + 1):
            conductor = conductores.pop(0) if conductores else None
            if conductor is None:
                reparto.incidencias.append(Incidencia("PENDIENTE", "JARDINERA_SIN_CONDUCTOR",
                                                      f"Falta conductor para la jardinera {codigo}J{n:02d}."))
            reparto.jardineras.append(Equipo(f"{codigo}J{n:02d}", codigo, t.inicio, t.fin, "JARDINERAS",
                                             {"Conductor": conductor}))
    reparto.reserva += conductores

    # Hipódromo: personal repartido según las salidas de cada turno.
    hipodromo = sorted((e for e in completos if e.categoria == "Hipodromo"), key=lambda e: e.id)
    turnos_hipo = conf.turnos_de("hipodromo")
    total_salidas = sum(salidas_por_turno.get(t.codigo, 0) for t in turnos_hipo) or 1
    for i, t in enumerate(turnos_hipo):
        if i == len(turnos_hipo) - 1:
            cuantos = len(hipodromo)
        else:
            cuantos = round(len(hipodromo) * salidas_por_turno.get(t.codigo, 0) / total_salidas)
        grupo, hipodromo = hipodromo[:cuantos], hipodromo[cuantos:]
        reparto.hipodromo.append(Equipo(f"{t.codigo}H", t.codigo, t.inicio, t.fin, "HIPODROMO",
                                        {f"Operario {n}": e for n, e in enumerate(grupo, 1)}))

    # Mandos intermedios: se alternan entre los turnos de mando.
    mandos = sorted((e for e in completos if e.categoria == "Mando intermedio"), key=lambda e: e.id)
    turnos_mando = conf.turnos_de("mandos")
    for i, e in enumerate(mandos):
        t = turnos_mando[i % len(turnos_mando)]
        reparto.mandos.append(Equipo(f"{t.codigo}{i // len(turnos_mando) + 1:02d}", t.codigo, t.inicio, t.fin,
                                     "MANDOS", {"Mando": e}))
    if not mandos:
        reparto.incidencias.append(Incidencia("PENDIENTE", "SIN_MANDO", "Ningún mando intermedio disponible."))

    # Parciales: refuerzo en los bancos de primera hora y de tarde.
    turnos_parc = conf.turnos_de("parciales")
    for i, e in enumerate(sorted(parciales, key=lambda e: e.id)):
        t = turnos_parc[i % len(turnos_parc)]
        reparto.parciales.append(Equipo(f"{t.codigo}-{e.id}", t.codigo, t.inicio, t.fin, "REFUERZO",
                                        {e.categoria: e}))
    return reparto
