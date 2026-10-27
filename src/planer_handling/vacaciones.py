"""Reparto de las vacaciones del año siguiente por puntos.

Cada persona pide periodos (quincenas) por orden de preferencia. Elige primero quien menos puntos
lleva acumulados (en empate, quien más antigüedad tiene) y cada periodo cuesta los puntos de su
temporada, que se suman a los suyos para el año siguiente: quien hoy se queda con agosto, otro año
elige más tarde. Por rondas: en cada ronda cada persona se lleva un periodo. En cada periodo solo
puede estar de vacaciones un cupo de cada función. Todo sale de `vacaciones` en la configuración.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .configuracion import Configuracion
from .importar.vuelos import clave

MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


@dataclass(frozen=True)
class Periodo:
    codigo: str          # "JUL-1": primera quincena de julio
    desde: date
    hasta: date


@dataclass
class Solicitud:
    empleado: str
    funcion: str
    puntos: float = 0.0
    antiguedad: date | None = None
    preferencias: list[str] = field(default_factory=list)
    asignados: list[str] = field(default_factory=list)
    conseguidas: int = 0             # cuántas de sus preferencias se le dieron

    def puntos_despues(self, valor: dict[str, float]) -> float:
        return self.puntos + sum(valor[p] for p in self.asignados)


def quincenas(anio: int) -> list[Periodo]:
    periodos = []
    for m in range(1, 13):
        fin_mes = (date(anio + m // 12, m % 12 + 1, 1) - timedelta(days=1))
        periodos.append(Periodo(f"{MESES[m - 1]}-1", date(anio, m, 1), date(anio, m, 15)))
        periodos.append(Periodo(f"{MESES[m - 1]}-2", date(anio, m, 16), fin_mes))
    return periodos


def valor_periodos(periodos: list[Periodo], conf: Configuracion) -> dict[str, float]:
    """Puntos que cuesta cada periodo: los de su temporada (config) o los de por defecto."""
    regla = conf.datos.get("vacaciones", {})
    valor = {p.codigo: regla.get("puntos_por_defecto", 1) for p in periodos}
    for temporada in regla.get("temporadas", []):
        for codigo in temporada["periodos"]:
            if codigo in valor:
                valor[codigo] = temporada["puntos"]
    return valor


def normalizar_periodo(texto) -> str | None:
    """"JUL-1", "jul 1", "1ª julio", "julio-2"… -> "JUL-1"."""
    t = clave(texto).replace("ª", "")
    if not t:
        return None
    mes = next((m for m in MESES if m in t[:4] or t.startswith(m) or f" {m}" in f" {t}"), None)
    numero = re.search(r"\b([12])\b|[-_ ]([12])$|^([12])", t)
    if not mes or not numero:
        return None
    return f"{mes}-{next(g for g in numero.groups() if g)}"


def leer_solicitudes(ruta: str | Path) -> list[Solicitud]:
    """Excel o CSV con Empleado, Función, Puntos, Antigüedad (opcional) y Preferencia 1, 2, 3…"""
    ruta = Path(ruta)
    df = pd.read_csv(ruta, dtype=str) if ruta.suffix.lower() == ".csv" else pd.read_excel(ruta, dtype=object)
    columnas = {clave(c): c for c in df.columns}
    buscar = lambda *nombres: next((columnas[n] for n in nombres if n in columnas), None)
    c_emp, c_fun = buscar("EMPLEADO", "NOMBRE", "CODIGO"), buscar("FUNCION", "DEPART.", "DEPART", "PUESTO")
    c_pun, c_ant = buscar("PUNTOS", "PUNTOS ACUMULADOS"), buscar("ANTIGUEDAD", "FECHA ALTA", "ALTA")
    c_pref = [columnas[c] for c in columnas if c.startswith("PREF")]
    if not c_emp or not c_pref:
        raise ValueError("El archivo de solicitudes necesita una columna Empleado y columnas Preferencia 1, 2…")
    solicitudes = []
    for _, fila in df.iterrows():
        nombre = str(fila[c_emp]).strip()
        if not nombre or nombre == "nan":
            continue
        antig = pd.to_datetime(fila[c_ant], dayfirst=True, errors="coerce") if c_ant else None
        prefs = [p for c in c_pref if (p := normalizar_periodo(fila[c]))]
        solicitudes.append(Solicitud(
            nombre, str(fila[c_fun]).strip() if c_fun and str(fila[c_fun]) != "nan" else "",
            float(fila[c_pun]) if c_pun and str(fila[c_pun]) not in ("", "nan") else 0.0,
            None if antig is None or pd.isna(antig) else antig.date(), list(dict.fromkeys(prefs))))
    return solicitudes


def cupos(solicitudes: list[Solicitud], periodos: list[Periodo], conf: Configuracion) -> dict[tuple[str, str], int]:
    """(periodo, función) -> cuántas personas de esa función pueden estar de vacaciones a la vez."""
    regla = conf.datos.get("vacaciones", {})
    por_funcion = Counter(s.funcion for s in solicitudes)
    resultado = {}
    for p in periodos:
        porcentaje = regla.get("cupo_por_defecto", 0.1)
        for temporada in regla.get("temporadas", []):
            if p.codigo in temporada["periodos"] and "cupo" in temporada:
                porcentaje = temporada["cupo"]
        for funcion, n in por_funcion.items():
            resultado[(p.codigo, funcion)] = max(1, math.floor(n * porcentaje))
    return resultado


def orden_de_eleccion(solicitudes: list[Solicitud]) -> list[Solicitud]:
    """Primero quien menos puntos lleva; en empate, quien más antigüedad tiene."""
    return sorted(solicitudes, key=lambda s: (s.puntos, s.antiguedad or date.max, s.empleado))


def repartir(solicitudes: list[Solicitud], anio: int, conf: Configuracion) -> dict[tuple[str, str], int]:
    """Asigna `periodos_por_persona` periodos a cada uno. Devuelve lo usado de cada cupo."""
    regla = conf.datos.get("vacaciones", {})
    por_persona = regla.get("periodos_por_persona", 2)
    periodos = quincenas(anio)
    valor = valor_periodos(periodos, conf)
    cupo = cupos(solicitudes, periodos, conf)
    usado: dict[tuple[str, str], int] = defaultdict(int)
    orden = orden_de_eleccion(solicitudes)
    for _ in range(por_persona):
        for s in orden:
            libre = lambda c: c not in s.asignados and usado[(c, s.funcion)] < cupo[(c, s.funcion)]
            elegido = next((c for c in s.preferencias if libre(c)), None)
            if elegido:
                s.conseguidas += 1
            else:
                # Sin preferencias libres: el periodo libre que menos puntos cuesta y menos lleno está.
                candidatos = [p.codigo for p in periodos if libre(p.codigo)]
                elegido = min(candidatos, key=lambda c: (valor[c], usado[(c, s.funcion)]), default=None)
            if elegido:
                s.asignados.append(elegido)
                usado[(elegido, s.funcion)] += 1
    return dict(usado)


def como_ausencias(solicitudes: list[Solicitud], anio: int) -> list[tuple[str, str, date, date]]:
    """(empleado, función, desde, hasta) de cada periodo asignado, para apuntarlos como vacaciones."""
    por_codigo = {p.codigo: p for p in quincenas(anio)}
    return [(s.empleado, s.funcion, por_codigo[c].desde, por_codigo[c].hasta)
            for s in solicitudes for c in sorted(s.asignados, key=lambda c: por_codigo[c].desde)]
