"""Códigos en lugar de nombres.

Cada persona recibe un código fijo (P0001, P0002…) la primera vez que aparece en un archivo, y el
mismo código todas las veces siguientes. No se guarda ningún nombre: el registro solo tiene una
huella (hash con una sal propia de este ordenador) de cada nombre y su código. Quien ya viene con
un código de empleado (EMP001, A1234…) lo conserva.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import replace
from pathlib import Path

from .importar.cuadrante import FilaCuadrante
from .importar.vuelos import clave

CODIGO = re.compile(r"^[A-Z]{1,4}-?\d{2,6}$")


def es_codigo(texto: str) -> bool:
    return bool(CODIGO.match(clave(texto).replace(" ", "")))


def _normal(nombre: str) -> str:
    """El mismo nombre escrito de otra forma ("PÉREZ, ANA" / "Perez Ana") da la misma huella."""
    return " ".join(sorted(clave(str(nombre).replace(",", " ")).split()))


class Codigos:
    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        if self.ruta.exists():
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        else:
            datos = {"sal": secrets.token_hex(16), "codigos": {}}
        self.sal: str = datos["sal"]
        self._codigos: dict[str, str] = datos["codigos"]

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps({"sal": self.sal, "codigos": self._codigos}, indent=0), encoding="utf-8")

    def codigo(self, nombre: str) -> str:
        nombre = str(nombre).strip()
        if es_codigo(nombre):
            return clave(nombre).replace(" ", "")
        huella = hashlib.sha256((self.sal + _normal(nombre)).encode()).hexdigest()
        if huella not in self._codigos:
            self._codigos[huella] = f"P{len(self._codigos) + 1:04d}"
            self._guardar()
        return self._codigos[huella]

    def filas(self, filas: list[FilaCuadrante]) -> list[FilaCuadrante]:
        return [replace(f, nombre=self.codigo(f.nombre)) for f in filas]

    def claves(self, datos: dict) -> dict:
        """Un diccionario por persona (contratos, formación…) con el código en lugar del nombre."""
        return {self.codigo(k): v for k, v in datos.items()}

    def lista(self, objetos: list, campo: str = "empleado") -> list:
        """Ausencias, solicitudes de vacaciones…: la misma lista con el código en `campo`."""
        return [replace(o, **{campo: self.codigo(getattr(o, campo))}) for o in objetos]

    def fichas(self, fichas: dict) -> dict:
        """Formación por persona (claves como las de habilitaciones.clave_persona)."""
        from .importar.habilitaciones import clave_persona
        return {clave_persona(self.codigo(k)): v for k, v in fichas.items()}
