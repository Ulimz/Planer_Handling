"""Perfiles de empresa: la configuración de cada empresa (y cliente) en su propio archivo.

Los perfiles de ejemplo están en `config/` y no se tocan. Los que crea el usuario se guardan en
`datos/empresas/` (fuera de Git) y solo guardan lo que cambia respecto al perfil del que parten
(`hereda:`), así se ve de un vistazo en qué se diferencian.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from .configuracion import Configuracion


@dataclass
class Perfil:
    clave: str          # nombre del archivo sin .yaml
    nombre: str         # el que ve el usuario
    ruta: Path
    editable: bool      # los de ejemplo no se sobrescriben: se guardan como empresa nueva


def nombre_de(conf: Configuracion, por_defecto: str) -> str:
    return (conf.datos.get("empresa") or {}).get("nombre") or por_defecto


def listar(carpeta_ejemplos: Path, carpeta_propias: Path) -> list[Perfil]:
    perfiles = []
    for carpeta, editable in ((carpeta_ejemplos, False), (carpeta_propias, True)):
        for ruta in sorted(carpeta.glob("*.yaml")) if carpeta.exists() else []:
            perfiles.append(Perfil(ruta.stem, nombre_de(Configuracion.cargar(ruta), ruta.stem), ruta, editable))
    return perfiles


def clave_de(nombre: str) -> str:
    """"Jet2 · Málaga" -> "jet2_malaga"."""
    t = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_") or "empresa"


def diferencias(base, nuevo):
    """Lo de `nuevo` que no está igual en `base` (las listas se comparan enteras)."""
    if isinstance(base, dict) and isinstance(nuevo, dict):
        resultado = {}
        for k, v in nuevo.items():
            if k not in base:
                resultado[k] = v
            elif (d := diferencias(base[k], v)) is not None:
                resultado[k] = d
        return resultado or None
    return None if base == nuevo else nuevo


def guardar(datos: dict, padre: Path, carpeta: Path, clave: str) -> Path:
    """Guarda `datos` como perfil `clave` que parte de `padre`: solo lo que cambia."""
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{clave}.yaml"
    cambios = diferencias(Configuracion.cargar(padre).datos, datos) or {}
    contenido = {"hereda": Path(os.path.relpath(padre, carpeta)).as_posix(), **cambios}
    ruta.write_text("# Perfil de empresa creado desde la web. Solo lo que cambia respecto a `hereda`.\n"
                    + yaml.safe_dump(contenido, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return ruta


def padre_de(ruta: Path) -> Path | None:
    """El perfil del que parte uno guardado (su `hereda`)."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return (ruta.parent / datos["hereda"]).resolve() if datos.get("hereda") else None
