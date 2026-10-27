"""Listado de ausencias del mes: una fila por ausencia con EMPLEADO (código o nombre como en el
cuadrante), DESDE, HASTA y MOTIVO (vacaciones, baja, permiso, formación...). Excel o CSV."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..mensual import Ausencia
from .vuelos import clave

ALIAS = {
    "EMPLEADO": ["EMPLEADO", "CODIGO", "NOMBRE", "TRABAJADOR", "APELLIDOS Y NOMBRE"],
    "DESDE": ["DESDE", "INICIO", "FECHA INICIO", "DEL"],
    "HASTA": ["HASTA", "FIN", "FECHA FIN", "AL"],
    "MOTIVO": ["MOTIVO", "TIPO", "CAUSA"],
}


def leer_ausencias(ruta: str | Path) -> list[Ausencia]:
    ruta = Path(ruta)
    df = pd.read_csv(ruta, sep=None, engine="python") if ruta.suffix.lower() == ".csv" else pd.read_excel(ruta)
    columnas = {}
    for campo, alias in ALIAS.items():
        columnas[campo] = next((c for c in df.columns if clave(c) in alias), None)
    faltan = [c for c in ("EMPLEADO", "DESDE") if columnas[c] is None]
    if faltan:
        raise ValueError(f"Al listado de ausencias le faltan las columnas: {', '.join(faltan)}.")
    ausencias = []
    for _, fila in df.iterrows():
        empleado = fila[columnas["EMPLEADO"]]
        desde = pd.to_datetime(fila[columnas["DESDE"]], dayfirst=True, errors="coerce")
        if pd.isna(empleado) or pd.isna(desde):
            continue
        hasta = pd.to_datetime(fila[columnas["HASTA"]], dayfirst=True, errors="coerce") if columnas["HASTA"] else desde
        motivo = fila[columnas["MOTIVO"]] if columnas["MOTIVO"] else "Ausencia"
        ausencias.append(Ausencia(str(empleado).strip(), desde.date(), (desde if pd.isna(hasta) else hasta).date(),
                                  "Ausencia" if pd.isna(motivo) else str(motivo).strip()))
    return ausencias
