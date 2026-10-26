from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .modelos import a_minutos


@dataclass
class Turno:
    codigo: str
    inicio: int
    fin: int


@dataclass
class Configuracion:
    datos: dict

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Configuracion":
        with open(ruta, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    @property
    def zona_horaria(self) -> str:
        return self.datos.get("zona_horaria", "Europe/Madrid")

    @property
    def inicio_ciclos(self) -> date:
        valor = self.datos["inicio_ciclos"]
        return valor if isinstance(valor, date) else date.fromisoformat(str(valor))

    @property
    def rotaciones(self) -> dict:
        return self.datos["rotaciones"]

    @property
    def turnos(self) -> dict[str, Turno]:
        resultado = {}
        for codigo, t in self.datos["turnos"].items():
            inicio, fin = a_minutos(t["inicio"]), a_minutos(t["fin"])
            if fin <= inicio:
                fin += 1440
            resultado[codigo] = Turno(codigo, inicio, fin)
        return resultado

    def turnos_de(self, colectivo: str) -> list[Turno]:
        todos = self.turnos
        return [todos[c] for c in self.datos[f"turnos_{colectivo}"]]

    @property
    def equipo_plataforma(self) -> list[str]:
        return self.datos["equipo_plataforma"]

    @property
    def servicio(self) -> dict:
        return self.datos["servicio"]

    @property
    def jardineras(self) -> dict:
        return self.datos["jardineras"]
