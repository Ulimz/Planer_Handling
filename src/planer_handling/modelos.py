"""Tipos de datos del motor. Las horas son minutos desde las 00:00 del día de trabajo
(pueden pasar de 1440 si el servicio cruza la medianoche)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def hhmm(minutos: int) -> str:
    minutos %= 1440
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def a_minutos(texto: str) -> int:
    h, m = texto.strip().split(":")
    return int(h) * 60 + int(m)


@dataclass
class Vuelo:
    """Una fila de la programación: llegada, salida o giro completo del mismo avión."""
    fecha: date
    vuelo_in: str = ""
    origen: str = ""
    sta: int | None = None
    vuelo_out: str = ""
    destino: str = ""
    std: int | None = None
    tipo_avion: str = ""
    puesto: str = ""          # "CONTACTO" o "REMOTO"; vacío si no se conoce
    fila_origen: str = ""

    @property
    def codigo(self) -> str:
        return "/".join(v for v in (self.vuelo_in, self.vuelo_out) if v)

    @property
    def remoto(self) -> bool:
        return self.puesto.upper().startswith("R")


@dataclass
class Tarea:
    """Trabajo que necesita un recurso (equipo o jardinera) durante [inicio, fin)."""
    id: str
    tipo: str                 # GIRO, SALIDA, LLEGADA, JARDINERA_LLEGADA, JARDINERA_SALIDA
    inicio: int
    fin: int
    vuelo: Vuelo


@dataclass
class Habilitacion:
    nombre: str
    caducidad: date | None = None

    def vigente(self, dia: date) -> bool:
        return self.caducidad is None or self.caducidad >= dia


@dataclass
class Empleado:
    id: str
    categoria: str
    contrato: str
    rotacion: str = ""        # "6x3-A", "4x4-2"... vacío para contratos sin rotación fija
    horas_turno: int = 8
    habilitaciones: list[Habilitacion] = field(default_factory=list)
    llamamiento: tuple[date, date] | None = None
    alta: date | None = None
    nombre: str = ""

    def habilitado(self, puesto: str, dia: date) -> bool:
        return any(h.nombre == puesto and h.vigente(dia) for h in self.habilitaciones)


@dataclass
class Equipo:
    codigo: str
    turno: str
    inicio: int
    fin: int
    seccion: str = "GRUPOS"   # GRUPOS, JARDINERAS, HIPODROMO
    miembros: dict[str, Empleado | None] = field(default_factory=dict)  # puesto -> empleado

    @property
    def completo(self) -> bool:
        return all(self.miembros.values())


@dataclass
class Incidencia:
    gravedad: str             # AVISO o PENDIENTE, como en PARRITRON
    codigo: str
    detalle: str
    referencia: str = ""
