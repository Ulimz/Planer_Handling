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
# Al reorganizar un horario publicado (en las mismas unidades que 1 franja de 15 min sin cubrir = 1000).
COSTE_CAMBIO = 5000          # mover a alguien compensa si tapa más de una hora de hueco de un operario
COSTE_IRREGULAR = 6000
COSTE_LLAMAR_LIBRE = 10000
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
    contrato: str = ""
    duraciones: list[int] = field(default_factory=list)   # minutos posibles; vacío = solo `duracion`
    horario_fijo: bool = False          # concreción horaria: entra siempre a su hora habitual
    jornada_minima: int = 0             # minutos por debajo de los que no se recorta su jornada
    horas_mes: list[float] = field(default_factory=list)  # [mínimo, máximo] del convenio (aviso)

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


def aprender_perfiles(filas: list[FilaCuadrante], dias: list[date], conf: Configuracion,
                      contratos: dict[str, str] | None = None) -> list[Perfil]:
    """`contratos`: nombre de la persona -> tipo de contrato (TC, TP…, ver `contratos` en la config)."""
    reglas = conf.datos.get("contratos", {})
    contrato_de = {clave(n): c for n, c in (contratos or {}).items()}
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
        p.contrato = contrato_de.get(clave(fila.nombre), "")
        regla = reglas.get(p.contrato, {})
        if not p.contrato and p.duracion < 7 * 60 + 30:
            regla = reglas.get(conf.datos.get("contrato_parcial_por_defecto", ""), {})
        p.horario_fijo = bool(regla.get("horario_fijo"))
        p.horas_mes = list(regla.get("horas_mes") or [])
        if regla.get("jornadas_h") and not p.horario_fijo:
            p.duraciones = [int(h * 60) for h in regla["jornadas_h"]]
            if len(p.duraciones) == 1:
                p.duracion, p.duraciones, p.partido = p.duraciones[0], [], None
            else:
                media = p.minutos_referencia / max(1, p.dias_referencia)
                p.jornada_minima = max(min(p.duraciones),
                                       int(conf.datos.get("jornada_minima_respecto_referencia", 0) * media) // PASO * PASO)
                # El optimizador le pone la jornada más larga posible (cubre más) y luego se recorta
                # lo que sobre (ver _recortar).
                p.duracion = max(p.duraciones)
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
    if perfil.horario_fijo:
        inicio = perfil.inicio_habitual.get(fase) or perfil.inicio_habitual[""]
        return [[(inicio, inicio + perfil.duracion)]]
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
                   ausentes: dict[str, str] | None = None,
                   actual: dict[str, list[tuple[int, int]]] | None = None,
                   coste_tl_pb_operario: int = 0,
                   costes_cambio: dict[str, tuple[int | None, int | None]] | None = None) -> list[Jornada]:
    """Horarios del día. Con `actual` (el horario ya publicado de ese día) reorganiza: mantiene a
    cada uno en su horario salvo que haga falta moverlo para cubrir a los ausentes, y solo llama
    a alguien que libra si no hay otra forma.
    `coste_tl_pb_operario`: lo que cuesta cada franja en que un TL o PB que sobra hace de operario.
    Con 0 se cuenta con ellos como un operario más; con un coste, solo si hace falta y si no
    quedan de refuerzo.
    `costes_cambio` (al reorganizar): id -> (coste de moverle el horario, coste de llamarle en su día
    libre). None = no se puede (por contrato o por falta de preaviso, ver `reglas_cambio`)."""
    modelo = cp_model.CpModel()
    n = franjas_del_dia()
    cubre: dict[str, list[list]] = {rol: [[] for _ in range(n)] for rol in PLANIFICADOS}
    eleccion: dict[tuple[str, int], tuple[cp_model.IntVar, list[tuple[int, int]]]] = {}
    coste = []
    fijas: list[Jornada] = []
    reserva: list[tuple[str, int]] = []
    coste_opcion: dict[tuple[str, int], int] = {}

    for p in perfiles:
        e = p.empleado
        if e.id in (ausentes or {}):
            continue
        pos = p.posicion(dia, referencia)
        fase = p.fases.get(pos, "") if pos is not None else ""
        if actual is not None:
            publicado = actual.get(e.id)
            trabaja = True if publicado else None
            if publicado:
                fase = "M" if publicado[0][0] < MEDIODIA else "T"
        else:
            publicado = None
            trabaja = p.trabaja(dia, referencia)
            if trabaja is False:
                continue
        if e.categoria not in PLANIFICADOS:
            # Jardineras, hipódromo y mandos: mantienen su horario (el publicado o el habitual).
            if publicado:
                fijas.append(Jornada(p, dia, publicado))
            elif trabaja:
                inicio = p.inicio_habitual.get(fase) or p.inicio_habitual[""]
                fijas.append(Jornada(p, dia, [(inicio, inicio + p.duracion)]))
            continue
        if trabaja is None and actual is None and dias_usados.get(e.id, 0) >= p.dias_referencia:
            continue
        coste_mover, coste_llamar = COSTE_CAMBIO, COSTE_IRREGULAR if p.patron == "irregular" else COSTE_LLAMAR_LIBRE
        if actual is not None and costes_cambio and e.id in costes_cambio:
            coste_mover, coste_llamar = costes_cambio[e.id]
            if not publicado and coste_llamar is None:
                continue                   # no se le puede llamar en su día libre
        opciones = _opciones(p, fase, fin_anterior.get(e.id))
        if publicado and coste_mover is None:
            opciones = [publicado]         # no se le puede mover el horario
        elif publicado and publicado not in opciones:
            opciones.append(publicado)
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
            if actual is None:
                coste_opcion[(e.id, n_opcion)] = abs(tramos[0][0] - habitual) // PASO   # parecido a su horario
            elif tramos != publicado:
                # Cambiar un horario ya publicado cuesta: solo si cubre lo que falta.
                coste_opcion[(e.id, n_opcion)] = ((coste_mover if publicado else 0)
                                                  + abs(tramos[0][0] - (publicado or tramos)[0][0]) // PASO)
            coste.append(coste_opcion.get((e.id, n_opcion), 0) * x)
        # Punto de partida para el optimizador (y plan de reserva): su horario publicado o el habitual.
        if publicado:
            habitual_n = opciones.index(publicado)
            reserva.append((e.id, habitual_n))
        elif trabaja:
            habitual_n = min(range(len(opciones)), key=lambda k: (len(opciones[k]), abs(opciones[k][0][0] - habitual)))
            reserva.append((e.id, habitual_n))
        for n_opcion, x in enumerate(variables):
            modelo.AddHint(x, bool(trabaja) and n_opcion == habitual_n)
        if trabaja:
            modelo.AddExactlyOne(variables)
        else:
            modelo.AddAtMostOne(variables)
            # Llamar a un irregular solo si hace falta; a alguien que libra, menos todavía.
            llamar = 50 if actual is None else coste_llamar
            coste.append(llamar * sum(variables))

    por_id = {p.empleado.id: p for p in perfiles}
    plan_reserva = [Jornada(por_id[eid], dia, eleccion[(eid, n_op)][1]) for eid, n_op in reserva]
    cubre_reserva = cobertura(plan_reserva)
    coste_reserva = sum(coste_opcion.get(r, 0) for r in reserva)
    deficit = []
    for k in range(n):
        tl, pb, op = (sum(cubre[r][k]) for r in ("TL", "PB/TOW", "Operario"))
        # Un TL o un PB que sobra en esa franja puede hacer de operario (según la empresa, con un coste).
        extra_tl = modelo.NewIntVar(0, len(perfiles), f"xtl{k}")
        extra_pb = modelo.NewIntVar(0, len(perfiles), f"xpb{k}")
        faltas = {r: modelo.NewIntVar(0, 10 * len(perfiles), f"f{r}{k}") for r in PLANIFICADOS}
        modelo.Add(tl - extra_tl + faltas["TL"] >= demanda_dia["TL"][k])
        modelo.Add(pb - extra_pb + faltas["PB/TOW"] >= demanda_dia["PB/TOW"][k])
        modelo.Add(op + extra_tl + extra_pb + faltas["Operario"] >= demanda_dia["Operario"][k])
        modelo.Add(extra_tl <= tl)
        modelo.Add(extra_pb <= pb)
        deficit += [3000 * faltas["TL"], 3000 * faltas["PB/TOW"], 1000 * faltas["Operario"],
                    coste_tl_pb_operario * (extra_tl + extra_pb)]
        # Pista completa (también de estas variables): el optimizador parte del plan de reserva (el
        # horario publicado o el habitual) y siempre tiene una solución aunque se le acabe el tiempo.
        r_tl, r_pb, r_op = (cubre_reserva[r][k] for r in ("TL", "PB/TOW", "Operario"))
        sobra_tl, sobra_pb = max(0, r_tl - demanda_dia["TL"][k]), max(0, r_pb - demanda_dia["PB/TOW"][k])
        hace_falta = max(0, demanda_dia["Operario"][k] - r_op)
        usa_tl = min(sobra_tl, hace_falta)
        usa_pb = min(sobra_pb, hace_falta - usa_tl)
        falta = {"TL": max(0, demanda_dia["TL"][k] - r_tl), "PB/TOW": max(0, demanda_dia["PB/TOW"][k] - r_pb),
                 "Operario": hace_falta - usa_tl - usa_pb}
        modelo.AddHint(extra_tl, usa_tl)
        modelo.AddHint(extra_pb, usa_pb)
        for r in PLANIFICADOS:
            modelo.AddHint(faltas[r], falta[r])
        coste_reserva += (3000 * (falta["TL"] + falta["PB/TOW"]) + 1000 * falta["Operario"]
                          + coste_tl_pb_operario * (usa_tl + usa_pb))
    modelo.Minimize(sum(deficit) + sum(coste))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = segundos
    solver.parameters.num_workers = 8
    estado = solver.Solve(modelo)
    peor = estado == cp_model.FEASIBLE and solver.ObjectiveValue() > coste_reserva
    if estado not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or peor:
        # Sin tiempo para encontrar nada mejor: cada uno con su horario habitual (o el publicado).
        jornadas = plan_reserva
    else:
        jornadas = [Jornada(por_id[eid], dia, tramos) for (eid, _), (x, tramos) in eleccion.items() if solver.Value(x)]
    if actual is None:
        _recortar(jornadas, demanda_dia, contar_tl_pb=coste_tl_pb_operario == 0)
    return fijas + jornadas


def _recortar(jornadas: list[Jornada], demanda_dia: dict[str, list[int]], contar_tl_pb: bool = True) -> None:
    """Acorta por los extremos las jornadas de quien tiene horas variables (parciales) mientras
    el trozo que se quita sobre en esa franja. Así no se dan más horas de las que piden los vuelos.
    Sin `contar_tl_pb` no se quitan horas de operario contando con un TL o PB que sobra: ese queda
    de refuerzo."""
    cob = cobertura(jornadas)
    n = franjas_del_dia()

    def puede_quitar(rol: str, k: int) -> bool:
        tl, pb, op = (cob[r][k] - (r == rol) for r in ("TL", "PB/TOW", "Operario"))
        dtl, dpb, dop = (demanda_dia[r][k] for r in ("TL", "PB/TOW", "Operario"))
        if not contar_tl_pb and rol == "Operario" and op < dop:
            return False
        return tl >= dtl and pb >= dpb and op + (tl - dtl) + (pb - dpb) >= dop

    for j in sorted(jornadas, key=lambda j: -j.minutos):
        p = j.perfil
        rol = p.empleado.categoria
        if not p.duraciones or rol not in cob:
            continue
        minimo = max(min(p.duraciones), p.jornada_minima)
        cambiado = True
        while cambiado and j.minutos - PASO >= minimo:
            cambiado = False
            for extremo in (0, -1):
                inicio, fin = j.tramos[extremo]
                k = _franja(inicio) if extremo == 0 else _franja(fin - 1)
                if fin - inicio > PASO and 0 <= k < n and puede_quitar(rol, k) and j.minutos - PASO >= minimo:
                    j.tramos[extremo] = (inicio + PASO, fin) if extremo == 0 else (inicio, fin - PASO)
                    cob[rol][k] -= 1
                    cambiado = True


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


def coste_tl_pb_operario(conf: Configuracion) -> int:
    regla = conf.datos.get("tl_pb_como_operario", {})
    if not regla.get("permitido", True):
        return 10 ** 6      # en la práctica, nunca: antes se deja el hueco sin cubrir
    return int(regla.get("coste", 0))


def planificar_mes(vuelos_por_dia: dict[date, list[Vuelo]], perfiles: list[Perfil], referencia: date,
                   conf: Configuracion, segundos_por_dia: float = 10,
                   ausencias: list[Ausencia] | None = None, progreso=None) -> CuadranteMes:
    """`progreso(dia, hechos, total)`, si se pasa, se llama al terminar cada día (para la web)."""
    fin_anterior: dict[str, int] = {}
    dias_usados: Counter = Counter()
    dias = []
    for dia in sorted(vuelos_por_dia):
        demanda_dia = demanda_del_dia(vuelos_por_dia[dia], conf)
        ausentes = ausentes_del_dia(ausencias or [], perfiles, dia)
        jornadas = planificar_dia(dia, demanda_dia, perfiles, referencia, fin_anterior, dias_usados,
                                  segundos_por_dia, ausentes, coste_tl_pb_operario=coste_tl_pb_operario(conf))
        fin_anterior = {j.perfil.empleado.id: j.fin for j in jornadas}
        dias_usados.update(j.perfil.empleado.id for j in jornadas)
        dias.append(DiaPlanificado(dia, len(vuelos_por_dia[dia]), demanda_dia, cobertura(jornadas), jornadas,
                                   ausentes))
        if progreso:
            progreso(dia, len(dias), len(vuelos_por_dia))
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


# --- 4. Reorganizar un cuadrante ya publicado por ausencias ---------------------------------

@dataclass
class Cambio:
    dia: date
    empleado: str
    funcion: str
    antes: str
    despues: str
    tipo: str                           # "Ausencia", "Cambio de horario", "Llamado en día libre"
    contrato: str = ""
    preaviso: int | None = None         # días entre el aviso y el cambio
    horas: float = 0.0                  # horas fuera de lo que tenía publicado
    tipo_horas: str = ""                # según el convenio (ver `cambios_publicado` en la config)


def _minutos_fuera(antes, despues) -> int:
    """Minutos de `despues` que no estaban en `antes`."""
    dentro = {m for i, f in (antes or []) for m in range(i, f)}
    return sum(1 for i, f in (despues or []) for m in range(i, f) if m not in dentro)


def es_parcial(p: Perfil, conf: Configuracion) -> bool:
    """Contrato a tiempo parcial (o sin contrato conocido y con jornada variable)."""
    return (p.contrato in conf.datos.get("cambios_publicado", {}).get("parciales", [])
            or (not p.contrato and bool(p.duraciones)))


def reglas_cambio(p: Perfil, preaviso: int, usadas_mes: int, conf: Configuracion
                  ) -> tuple[tuple[int | None, int | None], str, str]:
    """Qué cuesta moverle el horario y llamarle en su día libre a esta persona con este preaviso
    (None = no se puede), y cómo se llaman esas horas si se le mueve o se le llama.
    Las reglas están en `cambios_publicado` de la configuración (las de Azul son un ejemplo)."""
    reglas = conf.datos.get("cambios_publicado", {})
    if p.horario_fijo:
        return (None, None), "", ""
    if es_parcial(p, conf):
        if preaviso >= reglas.get("preaviso_complementarias_dias", 0):
            texto = reglas.get("texto_complementarias", "Horas complementarias")
            return (COSTE_CAMBIO * 3 // 5, COSTE_IRREGULAR), texto, texto
        limite = reglas.get("complementarias_especiales_mes_h")
        if limite is not None and usadas_mes >= limite * 60:
            return (None, None), "", ""
        texto = reglas.get("texto_especiales", "Horas complementarias especiales")
        return (COSTE_CAMBIO, COSTE_LLAMAR_LIBRE), texto, texto + reglas.get("texto_dia_libre", "")
    minimo = reglas.get("preaviso_horario_completo_dias")
    mover = None if minimo is not None and preaviso < minimo else COSTE_CAMBIO
    return (mover, COSTE_LLAMAR_LIBRE), "", reglas.get("texto_completo_dia_libre", "Horas extra")


def _texto(tramos) -> str:
    return " + ".join(f"{hhmm(i)}-{hhmm(f)}" for i, f in tramos) if tramos else "Libre"


def reorganizar(filas: list[FilaCuadrante], dias_mes: list[date], vuelos_por_dia: dict[date, list[Vuelo]],
                ausencias: list[Ausencia], conf: Configuracion, segundos_por_dia: float = 10,
                progreso=None, contratos: dict[str, str] | None = None,
                aviso: date | None = None) -> tuple[CuadranteMes, list[Cambio]]:
    """Rehace los días de `vuelos_por_dia` de un cuadrante ya publicado para cubrir a quien falta,
    moviendo a las menos personas posibles. El resto de días se queda como estaba.
    `aviso`: día en que se comunican los cambios (por defecto hoy). Con el contrato de cada persona y
    los días de preaviso se decide a quién se puede mover y qué tipo de horas genera."""
    aviso = aviso or date.today()
    marcas = conf.datos.get("marcas", {})
    perfiles = aprender_perfiles(filas, dias_mes, conf, contratos)
    especiales: Counter = Counter()      # minutos por persona con poco preaviso en el mes
    fila_de = {f.nombre: f for f in filas}
    cambios: list[Cambio] = []
    dias: list[DiaPlanificado] = []
    fin_anterior: dict[str, int] = {}
    vacia = {rol: [0] * franjas_del_dia() for rol in PLANIFICADOS}
    for n, dia in enumerate(dias_mes, 1):
        registradas = ausentes_del_dia(ausencias, perfiles, dia)     # las del registro (nuevas)
        actual, ausentes = {}, dict(registradas)                      # más las que ya traía el cuadrante
        for p in perfiles:
            jornada = fila_de[p.empleado.nombre].jornadas.get(dia)
            if not (jornada and jornada.tramos):
                continue
            marca = marcas.get(jornada.marca)
            if marca and not marca["disponible"]:
                ausentes.setdefault(p.empleado.id, marca["motivo"])
            else:
                actual[p.empleado.id] = jornada.tramos
        if dia in vuelos_por_dia:
            # Objetivo: recuperar la cobertura que tenía el horario publicado (sin pasar de lo que piden
            # los vuelos). Así solo se mueve gente para tapar los huecos de los ausentes.
            demanda_vuelos = demanda_del_dia(vuelos_por_dia[dia], conf)
            publicada = cobertura([Jornada(p, dia, fila_de[p.empleado.nombre].jornadas[dia].tramos)
                                   for p in perfiles if p.empleado.id in actual or p.empleado.id in registradas
                                   if fila_de[p.empleado.nombre].jornadas.get(dia)
                                   and fila_de[p.empleado.nombre].jornadas[dia].tramos])
            demanda_dia = {r: [min(d, c) for d, c in zip(demanda_vuelos[r], publicada[r])] for r in PLANIFICADOS}
            preaviso = (dia - aviso).days
            reglas = {p.empleado.id: reglas_cambio(p, preaviso, especiales[p.empleado.id], conf) for p in perfiles}
            jornadas = planificar_dia(dia, demanda_dia, perfiles, dias_mes[0], fin_anterior, {}, segundos_por_dia,
                                      ausentes, actual, coste_tl_pb_operario(conf),
                                      {eid: costes for eid, (costes, _, _) in reglas.items()})
            nuevo = {j.perfil.empleado.id: j.tramos for j in jornadas}
            minimo_complementarias = conf.datos.get("cambios_publicado", {}).get("preaviso_complementarias_dias", 0)
            for p in perfiles:
                eid = p.empleado.id
                antes, despues = actual.get(eid), nuevo.get(eid)
                if eid in registradas and antes:
                    cambios.append(Cambio(dia, p.empleado.nombre, p.funcion, _texto(antes), ausentes[eid], "Ausencia",
                                          p.contrato, preaviso))
                elif eid not in ausentes and antes != despues:
                    tipo = "Cambio de horario" if antes else "Llamado en día libre"
                    fuera = _minutos_fuera(antes, despues)
                    _, si_mueve, si_llama = reglas[eid]
                    tipo_horas = (si_mueve if antes else si_llama) if fuera else ""
                    if fuera and es_parcial(p, conf) and preaviso < minimo_complementarias:
                        especiales[eid] += fuera
                    cambios.append(Cambio(dia, p.empleado.nombre, p.funcion, _texto(antes), _texto(despues), tipo,
                                          p.contrato, preaviso, round(fuera / 60, 2), tipo_horas))
            dp = DiaPlanificado(dia, len(vuelos_por_dia[dia]), demanda_dia, cobertura(jornadas), jornadas, ausentes)
        else:
            jornadas = [Jornada(p, dia, actual[p.empleado.id]) for p in perfiles if p.empleado.id in actual]
            dp = DiaPlanificado(dia, 0, vacia, cobertura(jornadas), jornadas, ausentes)
        fin_anterior = {j.perfil.empleado.id: j.fin for j in dp.jornadas}
        dias.append(dp)
        if progreso:
            progreso(dia, n, len(dias_mes))
    return CuadranteMes(dias, perfiles, dias_mes[0]), cambios
