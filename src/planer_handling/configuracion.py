from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .modelos import a_minutos


def _mezclar(base: dict, cambios: dict) -> dict:
    resultado = dict(base)
    for clave, valor in cambios.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _mezclar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


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
        """Con `hereda: otro.yaml` (relativo a este archivo) parte de esa configuración y solo cambia
        lo que este archivo dice. Así cada empresa tiene su perfil sin copiar el de otra."""
        ruta = Path(ruta)
        with open(ruta, encoding="utf-8") as f:
            datos = yaml.safe_load(f) or {}
        base = datos.pop("hereda", None)
        if base:
            datos = _mezclar(cls.cargar(ruta.parent / base).datos, datos)
        return cls(datos)

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
