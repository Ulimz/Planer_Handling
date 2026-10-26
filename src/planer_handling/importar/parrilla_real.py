"""Lectura de los vuelos de una parrilla diaria ya hecha (una hoja por día, como "15-10").

Cabeceras en la fila 4: Orig. | N.Vuelo | Dest. | N.Vuelo | Matricula | Pk | ETA | STA | STD | ... | Grupo.
La llegada ocupa Orig. y las dos columnas de N.Vuelo (compañía y número); la salida, Dest. y las dos
siguientes. Las horas son locales. Devuelve también el grupo que hizo cada vuelo, para comparar.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import load_workbook

from ..modelos import Vuelo
from .vuelos import clave


def _minutos(valor) -> int | None:
    if isinstance(valor, (datetime, time)):
        return valor.hour * 60 + valor.minute
    m = re.match(r"\s*(\d{1,2}):(\d\d)", str(valor or ""))
    return int(m[1]) * 60 + int(m[2]) if m else None


FIN_DE_NOCHE = 4 * 60  # antes de las 04:00 cuenta como la noche siguiente


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def leer_vuelos_parrilla(ruta: str | Path, hoja: str, dia: date) -> tuple[list[Vuelo], dict[str, str]]:
    libro = load_workbook(ruta, data_only=True, read_only=True)
    ws = libro[hoja]
    filas = list(ws.iter_rows(min_row=1, max_row=400, values_only=True))
    fila_cab = next((i for i, f in enumerate(filas[:15]) if "N.VUELO" in [clave(v) for v in f]), None)
    if fila_cab is None:
        raise ValueError(f"La hoja {hoja} no tiene la cabecera N.Vuelo de una parrilla diaria.")
    cab = [clave(v) for v in filas[fila_cab]]
    # Algunas hojas llegan con cabeceras borradas; el orden de columnas es siempre el mismo.
    c_dest, c_sta, c_std = cab.index("DEST."), cab.index("STA"), cab.index("STD")
    c_orig = cab.index("ORIG.") if "ORIG." in cab else c_dest - 3
    c_pk = cab.index("PK") if "PK" in cab else c_sta - 2
    c_grupo = cab.index("GRUPO") if "GRUPO" in cab else None

    vuelos, grupos = [], {}
    for n, f in enumerate(filas[fila_cab + 1:], fila_cab + 2):
        compania_in, compania_out = _texto(f[c_orig + 1]), _texto(f[c_dest + 1])
        if not (re.fullmatch(r"[A-Z0-9]{2}", compania_in) or re.fullmatch(r"[A-Z0-9]{2}", compania_out)):
            continue
        v = Vuelo(dia, fila_origen=f"{hoja}!{n}", tipo_avion="")
        if compania_in and _texto(f[c_orig + 2]):
            v.vuelo_in, v.origen, v.sta = compania_in + _texto(f[c_orig + 2]), _texto(f[c_orig]), _minutos(f[c_sta])
        if compania_out and _texto(f[c_dest + 2]):
            v.vuelo_out, v.destino, v.std = compania_out + _texto(f[c_dest + 2]), _texto(f[c_dest]), _minutos(f[c_std])
        if v.sta is None and v.std is None:
            continue
        # La parrilla de un día acaba con llegadas pasada la medianoche (00:05, 01:00...):
        # son de esta misma noche, no de la madrugada anterior.
        if v.sta is not None and v.sta < FIN_DE_NOCHE:
            v.sta += 1440
        if v.std is not None and v.std < FIN_DE_NOCHE:
            v.std += 1440
        v.puesto = _texto(f[c_pk])
        partes = [v]
        if v.sta is not None and v.std is not None and v.std < v.sta:
            # Salida antes que la llegada en la misma fila: no es un giro, son dos servicios.
            salida = Vuelo(dia, vuelo_out=v.vuelo_out, destino=v.destino, std=v.std,
                           puesto=v.puesto, fila_origen=v.fila_origen, tipo_avion="")
            v.vuelo_out, v.destino, v.std = "", "", None
            partes.append(salida)
        for parte in partes:
            vuelos.append(parte)
            if c_grupo is not None:
                grupos[parte.codigo] = _texto(f[c_grupo])
    return vuelos, grupos
