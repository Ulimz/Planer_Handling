"""Cuadrante del mes a partir de la programación de vuelos del mes.

Parte de un cuadrante anterior (normalmente el del mes pasado) para conocer a cada persona:
su función, qué días trabaja (la rotación continúa sin reiniciarse), si cada día de su ciclo
es de mañana o de tarde y cuántas horas suele hacer al día. Con eso el motor:

1. Calcula la demanda de cada día: equipos necesarios cada 15 minutos según los vuelos.
2. Deja fijos los días de trabajo de quien sigue una rotación (6x3, 4x4) y decide su hora de
   entrada para cubrir la demanda. A quien no sigue una rotación lo llama solo cuando hace falta,
   sin pasar de los días que hizo en el mes de referencia.
3. Quien hacía turnos partidos puede recibir un partido (sus dos tramos habituales con una
   pausa de 1 a 5 horas) o un bloque seguido, lo que cubra mejor.
4. Respeta 12 horas de descanso entre jornadas y deja fuera a quien está de vacaciones, baja o
   permiso según el listado de ausencias.

Lo que no sabe todavía: la demanda de jardineras e hipódromo (esas personas mantienen su
horario habitual).
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from ortools.sat.python import cp_model

from . import demanda
from .configuracion import Configuracion
from .desde_cuadrante import empleados_desde_cuadrante
from .importar.cuadrante import FilaCuadrante
from .importar.vuelos import clave
from .modelos import Empleado, Vuelo, hhmm

PASO = 15
DESCANSO_MINIMO = 12 * 60
PAUSAS_PARTIDO = (60, 120, 180, 240, 300)   # convenio: la interrupción va de 1 a 5 horas
MEDIODIA = 12 * 60
INICIO_MAS_TEMPRANO = 4 * 60
INICIO_MAS_TARDIO = 21 * 60
ROTACIONES = {"6x3": (6, 3), "4x4": (4, 4)}
AJUSTE_MINIMO_ROTACION = 0.9
# Por equipo de plataforma: 1 TL, 1 PB/TOW y 3 operarios (carretero, cintero y cuarto operario).
PERSONAS_POR_EQUIPO = {"TL": 1, "PB/TOW": 1, "Operario": 3}
PLANIFICADOS = set(PERSONAS_POR_EQUIPO)


@dataclass
class Perfil:
    """Lo que el cuadrante de referencia dice de una persona."""
    empleado: Empleado
    funcion: str
    patron: str                         # "6x3", "4x4" o "irregular"
    desfase: int = 0                    # posición en el ciclo el primer día de referencia
    fases: dict[int, str] = field(default_factory=dict)        # posición del ciclo -> "M" / "T"
    inicio_habitual: dict[str, int] = field(default_factory=dict)  # "M"/"T"/"" -> minuto de entrada
    duracion: int = 8 * 60              # minutos de una jornada típica
    partido: tuple[int, int, int] | None = None   # (primer tramo, pausa, segundo tramo) si hace partidos
    dias_referencia: int = 0
    minutos_referencia: int = 0

    def ciclo(self) -> tuple[int, int] | None:
        return ROTACIONES.get(self.patron)

    def posicion(self, dia: date, referencia: date) -> int | None:
        ciclo = self.ciclo()
        if not ciclo:
            return None
        return ((dia - referencia).days + self.desfase) % sum(ciclo)

    def trabaja(self, dia: date, referencia: date) -> bool | None:
        """True/False si sigue una rotación; None si es irregular (se le llama según demanda)."""
        pos = self.posicion(dia, referencia)
        return None if pos is None else pos < self.ciclo()[0]


@dataclass
class Jornada:
    perfil: Perfil
    dia: date
    tramos: list[tuple[int, int]]       # uno, o dos si es turno partido

    @property
    def inicio(self) -> int:
        return self.tramos[0][0]

    @property
    def fin(self) -> int:
        return self.tramos[-1][1]

    @property
    def minutos(self) -> int:
        return sum(f - i for i, f in self.tramos)


@dataclass
class Ausencia:
    empleado: str                       # código (C001) o nombre tal como aparece en el cuadrante
    desde: date
    hasta: date
    motivo: str = "Ausencia"


@dataclass
class DiaPlanificado:
    dia: date
    vuelos: int
    demanda: dict[str, list[int]]       # rol -> personas necesarias en cada franja de 15 min
    cobertura: dict[str, list[int]]
    jornadas: list[Jornada]
    ausentes: dict[str, str] = field(default_factory=dict)   # id de empleado -> motivo

    def deficit(self, rol: str) -> int:
        """Minutos-persona sin cubrir en el día para ese rol."""
        return PASO * sum(max(0, d - c) for d, c in zip(self.demanda[rol], self.cobertura[rol]))


@dataclass
class CuadranteMes:
    dias: list[DiaPlanificado]
    perfiles: list[Perfil]
    referencia: date


# --- 1. Aprender de un cuadrante anterior --------------------------------------------------

def _dias_trabajados(fila: FilaCuadrante, dias: list[date]) -> list[int]:
    return [1 if fila.jornadas.get(d) and fila.jornadas[d].tramos else 0 for d in dias]


def _mejor_rotacion(trabajo: list[int]) -> tuple[str, int, float]:
    mejor = ("irregular", 0, 0.0)
    for nombre, (on, off) in ROTACIONES.items():
        largo = on + off
        for desfase in range(largo):
            prevision = [1 if (i + desfase) % largo < on else 0 for i in range(len(trabajo))]
            ajuste = sum(a == b for a, b in zip(trabajo, prevision)) / len(trabajo)
            if ajuste > mejor[2]:
                mejor = (nombre, desfase, ajuste)
    return mejor


def aprender_perfiles(filas: list[FilaCuadrante], dias: list[date], conf: Configuracion) -> list[Perfil]:
    empleados, _ = empleados_desde_cuadrante(filas, conf)
    perfiles = []
    for fila, empleado in zip(filas, empleados):
        trabajo = _dias_trabajados(fila, dias)
        if not any(trabajo):
            continue
        patron, desfase, ajuste = _mejor_rotacion(trabajo)
        if ajuste < AJUSTE_MINIMO_ROTACION:
            patron, desfase = "irregular", 0
        p = Perfil(empleado, fila.funcion, patron, desfase, dias_referencia=sum(trabajo))
        duraciones, inicios_por_pos, inicios_por_fase = [], {}, {"M": [], "T": [], "": []}
        partidos = []
        for i, dia in enumerate(dias):
            jornada = fila.jornadas.get(dia)
            if not (jornada and jornada.tramos):
                continue
            minutos = sum(f - a for a, f in jornada.tramos)
            duraciones.append(minutos)
            p.minutos_referencia += minutos
            inicio = jornada.tramos[0][0]
            if len(jornada.tramos) == 2:
                (a1, f1), (a2, f2) = jornada.tramos
                partidos.append((f1 - a1, a2 - f1, f2 - a2))
            inicios_por_fase[""].append(inicio)
            if p.ciclo():
                inicios_por_pos.setdefault((i + desfase) % sum(p.ciclo()), []).append(inicio)
        p.duracion = int(statistics.median(duraciones))
        if partidos:
            p.partido = tuple(int(statistics.median(x[k] for x in partidos)) for k in range(3))
        for pos, inicios in inicios_por_pos.items():
            fase = Counter("M" if x < MEDIODIA else "T" for x in inicios).most_common(1)[0][0]
            p.fases[pos] = fase
            inicios_por_fase[fase] += [x for x in inicios if (x < MEDIODIA) == (fase == "M")]
        p.inicio_habitual = {f: int(statistics.median(x)) for f, x in inicios_por_fase.items() if x}
        perfiles.append(p)
    return perfiles


# --- 2. Demanda de un día -------------------------------------------------------------------

def emparejar_giros(vuelos: list[Vuelo], minimo: int = 25, maximo: int = 90) -> list[Vuelo]:
    """En las descargas mensuales muchas llegadas y salidas del mismo avión vienen en filas
    separadas (sin matrícula todavía). Une cada llegada suelta con la primera salida suelta
    entre `minimo` y `maximo` minutos después, que es como se trabaja: un solo giro."""
    llegadas = sorted((v for v in vuelos if v.sta is not None and v.std is None), key=lambda v: v.sta)
    salidas = sorted((v for v in vuelos if v.std is not None and v.sta is None), key=lambda v: v.std)
    resto = [v for v in vuelos if (v.sta is None) == (v.std is None)]
    usadas = set()
    for llegada in llegadas:
        salida = next((s for s in salidas if id(s) not in usadas and minimo <= s.std - llegada.sta <= maximo), None)
        if salida is None:
            resto.append(llegada)
            continue
        usadas.add(id(salida))
        resto.append(Vuelo(llegada.fecha, llegada.vuelo_in, llegada.origen, llegada.sta, salida.vuelo_out,
                           salida.destino, salida.std, llegada.tipo_avion or salida.tipo_avion,
                           llegada.puesto or salida.puesto, llegada.fila_origen))
    resto += [s for s in salidas if id(s) not in usadas]
    return sorted(resto, key=lambda v: min(x for x in (v.sta, v.std) if x is not None))


def franjas_del_dia() -> int:
    return (INICIO_MAS_TARDIO + 15 * 60 - INICIO_MAS_TEMPRANO) // PASO


def _franja(minuto: int) -> int:
    return (minuto - INICIO_MAS_TEMPRANO) // PASO


def demanda_del_dia(vuelos: list[Vuelo], conf: Configuracion) -> dict[str, list[int]]:
    """Equipos a la vez en cada franja (cada vuelo ocupa a un equipo su tiempo de servicio más el
    tránsito al siguiente) multiplicados por las personas de cada rol en un equipo."""
    tareas = demanda.tareas_plataforma(emparejar_giros(vuelos), conf)
    transito = conf.servicio["transito_entre_vuelos"]
    equipos = [0] * franjas_del_dia()
    for t in tareas:
        for k in range(max(0, _franja(t.inicio)), min(len(equipos), _franja(t.fin + transito - 1) + 1)):
            equipos[k] += 1
    return {rol: [n * e for e in equipos] for rol, n in PERSONAS_POR_EQUIPO.items()}


# --- 3. Horarios del día --------------------------------------------------------------------

def _opciones(perfil: Perfil, fase: str, fin_anterior: int | None) -> list[list[tuple[int, int]]]:
    """Jornadas posibles: un bloque de sus horas habituales y, si hace partidos, también dos
    tramos con sus duraciones habituales y una pausa de 1 a 5 horas."""
    inicios = _opciones_inicio(fase, fin_anterior)
    opciones = [[(i, i + perfil.duracion)] for i in inicios]
    if perfil.partido:
        primero, _, segundo = perfil.partido
        for i in inicios[::2]:
            for pausa in PAUSAS_PARTIDO:
                opciones.append([(i, i + primero), (i + primero + pausa, i + primero + pausa + segundo)])
    return opciones


def _opciones_inicio(fase: str, fin_anterior: int | None) -> list[int]:
    if fase == "M":
        desde, hasta = INICIO_MAS_TEMPRANO, MEDIODIA - PASO
    elif fase == "T":
        desde, hasta = MEDIODIA, INICIO_MAS_TARDIO
    else:
        desde, hasta = INICIO_MAS_TEMPRANO, INICIO_MAS_TARDIO
    if fin_anterior is not None:
        desde = max(desde, fin_anterior + DESCANSO_MINIMO - 1440)
    return list(range(desde - desde % PASO + (PASO if desde % PASO else 0), hasta + 1, PASO))


def planificar_dia(dia: date, demanda_dia: dict[str, list[int]], perfiles: list[Perfil], referencia: date,
                   fin_anterior: dict[str, int], dias_usados: dict[str, int], segundos: float = 10,
                   ausentes: dict[str, str] | None = None) -> list[Jornada]:
    modelo = cp_model.CpModel()
    n = franjas_del_dia()
    cubre: dict[str, list[list]] = {rol: [[] for _ in range(n)] for rol in PLANIFICADOS}
    eleccion: dict[tuple[str, int], tuple[cp_model.IntVar, list[tuple[int, int]]]] = {}
    coste = []
    fijas: list[Jornada] = []

    for p in perfiles:
        e = p.empleado
        trabaja = p.trabaja(dia, referencia)
        if trabaja is False or e.id in (ausentes or {}):
            continue
        pos = p.posicion(dia, referencia)
        fase = p.fases.get(pos, "") if pos is not None else ""
        if e.categoria not in PLANIFICADOS:
            # Jardineras, hipódromo y mandos: mantienen su horario habitual en los días de su rotación.
            if trabaja:
                inicio = p.inicio_habitual.get(fase) or p.inicio_habitual[""]
                fijas.append(Jornada(p, dia, [(inicio, inicio + p.duracion)]))
            continue
        if trabaja is None and dias_usados.get(e.id, 0) >= p.dias_referencia:
            continue
        opciones = _opciones(p, fase, fin_anterior.get(e.id))
        if not opciones:
            continue
        variables = []
        habitual = p.inicio_habitual.get(fase) or p.inicio_habitual[""]
        for n_opcion, tramos in enumerate(opciones):
            x = modelo.NewBoolVar(f"{e.id}_{n_opcion}")
            eleccion[(e.id, n_opcion)] = (x, tramos)
            variables.append(x)
            for inicio, fin in tramos:
                for k in range(max(0, _franja(inicio)), min(n, _franja(fin - 1) + 1)):
                    cubre[e.categoria][k].append(x)
            coste.append(abs(tramos[0][0] - habitual) // PASO * x)    # parecido a su horario de siempre
        if trabaja:
            modelo.AddExactlyOne(variables)
        else:
            modelo.AddAtMostOne(variables)
            coste.append(50 * sum(variables))                         # llamar a un irregular solo si hace falta

    deficit = []
    for k in range(n):
        tl, pb, op = (sum(cubre[r][k]) for r in ("TL", "PB/TOW", "Operario"))
        # Un TL o un PB que sobra en esa franja puede hacer de operario.
        extra_tl = modelo.NewIntVar(0, len(perfiles), f"xtl{k}")
        extra_pb = modelo.NewIntVar(0, len(perfiles), f"xpb{k}")
        faltas = {r: modelo.NewIntVar(0, 10 * len(perfiles), f"f{r}{k}") for r in PLANIFICADOS}
        modelo.Add(tl - extra_tl + faltas["TL"] >= demanda_dia["TL"][k])
        modelo.Add(pb - extra_pb + faltas["PB/TOW"] >= demanda_dia["PB/TOW"][k])
        modelo.Add(op + extra_tl + extra_pb + faltas["Operario"] >= demanda_dia["Operario"][k])
        modelo.Add(extra_tl <= tl)
        modelo.Add(extra_pb <= pb)
        deficit += [3000 * faltas["TL"], 3000 * faltas["PB/TOW"], 1000 * faltas["Operario"]]
    modelo.Minimize(sum(deficit) + sum(coste))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = segundos
    solver.parameters.num_workers = 8
    estado = solver.Solve(modelo)
    if estado not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"Sin solución para el {dia} ({solver.StatusName(estado)}).")
    por_id = {p.empleado.id: p for p in perfiles}
    jornadas = fijas + [Jornada(por_id[eid], dia, tramos)
                        for (eid, _), (x, tramos) in eleccion.items() if solver.Value(x)]
    return jornadas


def cobertura(jornadas: list[Jornada]) -> dict[str, list[int]]:
    n = franjas_del_dia()
    resultado = {rol: [0] * n for rol in PLANIFICADOS}
    for j in jornadas:
        rol = j.perfil.empleado.categoria
        if rol in resultado:
            for inicio, fin in j.tramos:
                for k in range(max(0, _franja(inicio)), min(n, _franja(fin - 1) + 1)):
                    resultado[rol][k] += 1
    return resultado


def ausentes_del_dia(ausencias: list[Ausencia], perfiles: list[Perfil], dia: date) -> dict[str, str]:
    """{id de empleado: motivo} de quien no está ese día. Se busca por código o por nombre."""
    por_clave = {}
    for p in perfiles:
        por_clave[clave(p.empleado.id)] = p.empleado.id
        por_clave[clave(p.empleado.nombre)] = p.empleado.id
    resultado = {}
    for a in ausencias:
        eid = por_clave.get(clave(a.empleado))
        if eid and a.desde <= dia <= a.hasta:
            resultado[eid] = a.motivo
    return resultado


def planificar_mes(vuelos_por_dia: dict[date, list[Vuelo]], perfiles: list[Perfil], referencia: date,
                   conf: Configuracion, segundos_por_dia: float = 10,
                   ausencias: list[Ausencia] | None = None) -> CuadranteMes:
    fin_anterior: dict[str, int] = {}
    dias_usados: Counter = Counter()
    dias = []
    for dia in sorted(vuelos_por_dia):
        demanda_dia = demanda_del_dia(vuelos_por_dia[dia], conf)
        ausentes = ausentes_del_dia(ausencias or [], perfiles, dia)
        jornadas = planificar_dia(dia, demanda_dia, perfiles, referencia, fin_anterior, dias_usados,
                                  segundos_por_dia, ausentes)
        fin_anterior = {j.perfil.empleado.id: j.fin for j in jornadas}
        dias_usados.update(j.perfil.empleado.id for j in jornadas)
        dias.append(DiaPlanificado(dia, len(vuelos_por_dia[dia]), demanda_dia, cobertura(jornadas), jornadas,
                                   ausentes))
    return CuadranteMes(dias, perfiles, referencia)


def dias_del_mes(anio: int, mes: int) -> list[date]:
    dia, resultado = date(anio, mes, 1), []
    while dia.month == mes:
        resultado.append(dia)
        dia += timedelta(days=1)
    return resultado


def texto_jornada(tramos: list[tuple[int, int]]) -> str:
    """Como en el cuadrante de la empresa: "05:00\\n09:20", y los partidos separados por una línea en blanco."""
    return "\n\n".join(f"{hhmm(i)}\n{hhmm(f)}" for i, f in tramos)
