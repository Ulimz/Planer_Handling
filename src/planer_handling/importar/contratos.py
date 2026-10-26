"""Tipo de contrato de cada persona: Excel o CSV con una columna de empleado (nombre como en el
cuadrante) y otra de contrato (TC, TP, FD…, los códigos de `contratos` en la configuración)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .vuelos import clave

ALIAS_EMPLEADO = ["EMPLEADO", "NOMBRE", "TRABAJADOR", "APELLIDOS Y NOMBRE"]


def leer_contratos(ruta: str | Path) -> dict[str, str]:
    ruta = Path(ruta)
    libro = {"": pd.read_csv(ruta, sep=None, engine="python")} if ruta.suffix.lower() == ".csv" \
        else pd.read_excel(ruta, sheet_name=None)
    for df in libro.values():
        empleado = next((c for c in df.columns if clave(c) in ALIAS_EMPLEADO), None)
        contrato = next((c for c in df.columns if clave(c).startswith("CONTRATO")), None)
        if empleado and contrato:
            return {str(e).strip(): str(c).strip().upper() for e, c in zip(df[empleado], df[contrato])
                    if pd.notna(e) and pd.notna(c) and str(c).strip()}
    raise ValueError("El archivo de contratos necesita una columna EMPLEADO y otra CONTRATO.")
