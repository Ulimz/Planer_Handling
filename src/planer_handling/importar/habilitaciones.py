"""Formación y habilitaciones de cada persona: Excel con bloques que empiezan por una fila de
cabecera con EMPLEADO, CONTRATO y una columna por habilitación (PCP, FORMACION CINTA, PBT…).
Puede haber varios bloques en una hoja, uno al lado del otro o uno debajo de otro. Qué significa
cada columna se dice en `habilitaciones_por_persona` de la configuración."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..configuracion import Configuracion
from ..modelos import Habilitacion
from .vuelos import clave


@dataclass
class Ficha:
    contrato: str = ""
    da: set[str] = field(default_factory=set)      # habilitaciones que tiene
    quita: set[str] = field(default_factory=set)   # habilitaciones que no tiene aunque su función las dé


def clave_persona(nombre) -> str:
    """'GARCIA LOPEZ, ANA' y 'GARCIA LOPEZ ANA' son la misma persona."""
    return clave(str(nombre).replace(",", " "))


def leer_habilitaciones(ruta: str | Path, conf: Configuracion) -> dict[str, Ficha]:
    reglas = conf.datos.get("habilitaciones_por_persona", {})
    columnas = {clave(c): r for c, r in reglas.get("columnas", {}).items()}
    si = {clave(x) for x in reglas.get("tiene", ["1"])}
    no = {clave(x) for x in reglas.get("no_tiene", ["0"])}
    alias = {clave(a): c for a, c in reglas.get("alias_contratos", {}).items()}
    fichas: dict[str, Ficha] = {}
    for df in pd.read_excel(ruta, sheet_name=None, header=None).values():
        celdas = df.map(clave).values.tolist()
        for i, fila in enumerate(celdas):
            for j, valor in enumerate(fila):
                if valor not in ("EMPLEADO", "NOMBRE"):
                    continue
                cabecera = {}
                for k in range(j + 1, len(fila)):
                    if not fila[k] or fila[k] in ("EMPLEADO", "NOMBRE"):
                        break
                    cabecera[k] = fila[k]
                for siguiente in celdas[i + 1:]:
                    nombre = siguiente[j]
                    if not nombre or nombre in ("EMPLEADO", "NOMBRE"):
                        break
                    ficha = fichas.setdefault(clave_persona(nombre), Ficha())
                    for k, titulo in cabecera.items():
                        dato = siguiente[k]
                        if titulo.startswith("CONTRATO"):
                            ficha.contrato = alias.get(dato, dato)
                        elif titulo in columnas:
                            regla = columnas[titulo]
                            if dato in si and not regla.get("solo_quita"):
                                ficha.da.update(regla["habilitaciones"])
                            elif dato in no:
                                ficha.quita.update(regla["habilitaciones"])
    if not fichas:
        raise ValueError("No hay ninguna fila de cabecera con EMPLEADO en el archivo de habilitaciones.")
    for ficha in fichas.values():
        ficha.quita -= ficha.da      # PBT a 0 y TBL a 1: sí puede hacer de PB/TOW
    return fichas


def aplicar(habilitaciones: list[Habilitacion], ficha: Ficha | None) -> list[Habilitacion]:
    """Las de su función, quitando las que la ficha dice que no tiene y sumando las que tiene."""
    if ficha is None:
        return habilitaciones
    nombres = [h.nombre for h in habilitaciones if h.nombre not in ficha.quita]
    nombres += sorted(ficha.da - set(nombres))
    return [Habilitacion(n) for n in nombres]
