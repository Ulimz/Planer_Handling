"""Formación de equipos de plataforma y reparto del resto de colectivos por turnos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .configuracion import Configuracion, Turno
from .modelos import Empleado, Equipo, Incidencia
from .operativa import Operativa, Recurso


@dataclass
class Reparto:
    equipos: list[Equipo] = field(default_factory=list)       # los del recurso principal
    jardineras: list[Equipo] = field(default_factory=list)    # los del resto de recursos
    hipodromo: list[Equipo] = field(default_factory=list)
    mandos: list[Equipo] = field(default_factory=list)
    parciales: list[Equipo] = field(default_factory=list)
    reserva: list[Empleado] = field(default_factory=list)
    incidencias: list[Incidencia] = field(default_factory=list)
    por_recurso: dict[str, list[Equipo]] = field(default_factory=dict)   # nombre del recurso -> equipos


def _habilitaciones_vigentes(e: Empleado, dia: date) -> int:
    return sum(1 for h in e.habilitaciones if h.vigente(dia))


def formar_equipos(personal: list[Empleado], necesarios: dict[str, int], turnos: dict[str, Turno],
                   puestos: list[str], dia: date, etiquetas: list[str] | None = None, letra: str = "",
                   seccion: str = "GRUPOS") -> tuple[list[Equipo], list[Empleado], list[Incidencia]]:
    """Forma `necesarios[turno]` equipos por turno. Cada puesto se cubre con quien tenga la
    habilitación vigente, prefiriendo a quien la tiene como categoría principal y reservando
    a los más polivalentes para los puestos que queden.
    `etiquetas`: nombre de cada puesto en el equipo (si un puesto se repite: Operario 1, Operario 2…).
    `letra`: va en el código del equipo, tras el turno (MP01 para un PB suelto)."""
    etiquetas = etiquetas or puestos
    # Se completan los equipos uno a uno, alternando turnos (M01, T01, N01, M02...), para que
    # si falta personal salgan menos equipos completos y no muchos equipos a medias.
    orden = []
    for n in range(1, max(necesarios.values(), default=0) + 1):
        for codigo, cantidad in necesarios.items():
            if n <= cantidad:
                t = turnos[codigo]
                orden.append(Equipo(f"{codigo}{letra}{n:02d}", codigo, t.inicio, t.fin, seccion,
                                    {p: None for p in etiquetas}))
    libres = list(personal)
    incidencias: list[Incidencia] = []
    for equipo in orden:
        for puesto, etiqueta in zip(puestos, etiquetas):
            candidatos = [e for e in libres if e.habilitado(puesto, dia)]
            if not candidatos:
                continue  # queda VACANTE; la validación lo señala como EQUIPO_INCOMPLETO
            elegido = min(candidatos, key=lambda e: (e.categoria != puesto, _habilitaciones_vigentes(e, dia), e.id))
            equipo.miembros[etiqueta] = elegido
            libres.remove(elegido)
    equipos = sorted(orden, key=lambda e: (list(necesarios).index(e.turno), e.codigo))
    return equipos, libres, incidencias


def _por_orden_de_codigo(recurso: Recurso, personal: list[Empleado], necesarios: dict[str, int],
                         turnos: dict[str, Turno]) -> tuple[list[Equipo], list[Empleado], list[Incidencia]]:
    """Un recurso de una persona de cierta categoría (la jardinera de Azul): se cubre por orden de
    código, turno a turno."""
    libres = sorted(personal, key=lambda e: e.id)
    equipos, incidencias = [], []
    puesto = recurso.etiquetas()[0]
    for codigo, cantidad in necesarios.items():
        t = turnos[codigo]
        for n in range(1, cantidad + 1):
            persona = libres.pop(0) if libres else None
            nombre = f"{codigo}{recurso.codigo}{n:02d}"
            if persona is None:
                incidencias.append(Incidencia("PENDIENTE", f"{recurso.nombre.upper()}_SIN_{puesto.upper()}",
                                              f"Falta {puesto.lower()} para la {recurso.nombre.lower()} {nombre}."))
            equipos.append(Equipo(nombre, codigo, t.inicio, t.fin, recurso.seccion, {puesto: persona}))
    return equipos, libres, incidencias


def categorias_reservadas(op: Operativa, conf: Configuracion) -> set[str]:
    """Categorías que no entran en un recurso salvo que este las pida: las que otros recursos
    piden expresamente y las de los colectivos que se planifican aparte (hipódromo y mandos)."""
    reservadas = {c for r in op.recursos for c in r.categorias}
    if conf.datos.get("turnos_hipodromo"):
        reservadas.add("Hipodromo")
    if conf.datos.get("turnos_mandos"):
        reservadas.add("Mando intermedio")
    return reservadas


def repartir(disponibles: list[Empleado], necesarios: dict[str, dict[str, int]],
             salidas_por_turno: dict[str, int], conf: Configuracion, dia: date) -> Reparto:
    """`necesarios`: nombre del recurso -> {turno: cuántos}. Los recursos se forman en el orden del
    perfil; quien no entra en uno puede entrar en el siguiente."""
    turnos = conf.turnos
    op = conf.operativa
    reparto = Reparto()
    parciales = [e for e in disponibles if e.contrato == "Tiempo parcial"]
    completos = [e for e in disponibles if e not in parciales]
    reservadas = categorias_reservadas(op, conf)

    libres = list(completos)
    sobrantes: list[Empleado] = []
    for recurso in op.recursos:
        if recurso.categorias:
            personal = [e for e in libres if e.categoria in recurso.categorias]
        else:
            fuera = reservadas | set(recurso.excluir_categorias)
            personal = [e for e in libres if e.categoria not in fuera]
        libres = [e for e in libres if e not in personal]
        if recurso.por_orden_de_codigo:
            equipos, resto, inc = _por_orden_de_codigo(recurso, personal, necesarios.get(recurso.nombre, {}), turnos)
        else:
            equipos, resto, inc = formar_equipos(personal, necesarios.get(recurso.nombre, {}), turnos,
                                                 recurso.puestos, dia, recurso.etiquetas(), recurso.codigo,
                                                 recurso.seccion)
        reparto.por_recurso[recurso.nombre] = equipos
        reparto.incidencias += inc
        if recurso is op.principal:
            reparto.equipos = equipos
        else:
            reparto.jardineras += equipos
        # Quien sobra de este recurso puede entrar en el siguiente; al final queda de reserva.
        if recurso.por_orden_de_codigo:
            sobrantes += resto
        else:
            libres = resto + libres
    aparte = reservadas - {c for r in op.recursos for c in r.categorias}   # hipódromo y mandos
    reparto.reserva = [e for e in libres if e.categoria not in aparte] + sobrantes

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
    turnos_mando = conf.turnos_de("mandos")
    mandos = sorted((e for e in completos if e.categoria == "Mando intermedio"), key=lambda e: e.id) if turnos_mando else []
    for i, e in enumerate(mandos):
        t = turnos_mando[i % len(turnos_mando)]
        reparto.mandos.append(Equipo(f"{t.codigo}{i // len(turnos_mando) + 1:02d}", t.codigo, t.inicio, t.fin,
                                     "MANDOS", {"Mando": e}))
    if turnos_mando and not mandos:
        reparto.incidencias.append(Incidencia("PENDIENTE", "SIN_MANDO", "Ningún mando intermedio disponible."))

    # Parciales: refuerzo en los bancos de primera hora y de tarde.
    turnos_parc = conf.turnos_de("parciales")
    for i, e in enumerate(sorted(parciales, key=lambda e: e.id) if turnos_parc else []):
        t = turnos_parc[i % len(turnos_parc)]
        reparto.parciales.append(Equipo(f"{t.codigo}-{e.id}", t.codigo, t.inicio, t.fin, "REFUERZO",
                                        {e.categoria: e}))
    return reparto
