"""Lectura de la plantilla (formato de scripts/generar_plantilla_ficticia.py)."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from ..modelos import Empleado, Habilitacion


def _fecha(valor) -> date | None:
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _texto(valor) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor).strip()


def leer_plantilla(ruta: str | Path) -> list[Empleado]:
    hojas = pd.read_excel(ruta, sheet_name=["Plantilla", "Habilitaciones"])
    habilitaciones: dict[str, list[Habilitacion]] = {}
    for _, fila in hojas["Habilitaciones"].iterrows():
        habilitaciones.setdefault(_texto(fila["id_empleado"]), []).append(
            Habilitacion(_texto(fila["habilitacion"]), _fecha(fila.get("fecha_caducidad")))
        )
    empleados = []
    for _, fila in hojas["Plantilla"].iterrows():
        emp_id = _texto(fila["id_empleado"])
        inicio, fin = _fecha(fila.get("llamamiento_inicio")), _fecha(fila.get("llamamiento_fin"))
        horas = fila.get("horas_turno")
        empleados.append(Empleado(
            id=emp_id,
            categoria=_texto(fila["categoria_principal"]),
            contrato=_texto(fila["contrato"]),
            rotacion=_texto(fila.get("rotacion")),
            horas_turno=int(horas) if horas is not None and not pd.isna(horas) else 8,
            habilitaciones=habilitaciones.get(emp_id, []),
            llamamiento=(inicio, fin) if inicio and fin else None,
            alta=_fecha(fila.get("fecha_alta")),
        ))
    return empleados
