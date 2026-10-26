"""Lectura de la programación de vuelos en los formatos que ya usa PARRITRON.

PACOTRON: FLIGHT DATE. | FLIGHT IN | ORIG | STA | FLIGHT OUT | DEST | STD
OMS:      FLIGHT DATE | ARRIVALS - FLT.NO. | PREV PRT | STA | DEPARTURES - FLT.NO. | NEXT PRT | STD

Las horas de estos archivos van en hora Zulu (UTC) y se pasan a hora local de la base.
Columnas opcionales: tipo de avión y puesto (contacto o remoto).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..modelos import Incidencia, Vuelo

CAMPOS = ["FECHA", "VUELO_IN", "ORIGEN", "STA", "VUELO_OUT", "DESTINO", "STD"]
FORMATOS = {
    "PACOTRON": ["FLIGHT DATE.", "FLIGHT IN", "ORIG", "STA", "FLIGHT OUT", "DEST", "STD"],
    "OMS": ["FLIGHT DATE", "ARRIVALS - FLT.NO.", "PREV PRT", "STA", "DEPARTURES - FLT.NO.", "NEXT PRT", "STD"],
}
OPCIONALES = {
    "TIPO": ["AC TYPE", "A/C TYPE", "TYPE", "TIPO", "TIPO AVION", "EQUIPO", "AIRCRAFT SUB"],
    "PUESTO": ["STAND", "STAND IN", "PUESTO", "PARKING", "POSICION"],
}


def clave(texto) -> str:
    texto = "" if texto is None or (isinstance(texto, float) and pd.isna(texto)) else str(texto)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().upper()


def _leer_tablas(ruta: Path) -> dict[str, pd.DataFrame]:
    if ruta.suffix.lower() == ".csv":
        texto = ruta.read_text(encoding="utf-8-sig")
        separador = ";" if texto.count(";") > texto.count(",") else ","
        return {ruta.name: pd.read_csv(ruta, header=None, dtype=str, sep=separador, encoding="utf-8-sig")}
    return pd.read_excel(ruta, sheet_name=None, header=None, dtype=object)


def _buscar_cabecera(tablas: dict[str, pd.DataFrame]):
    encontradas = []
    for hoja, df in tablas.items():
        for fila in range(min(20, len(df))):
            cabeceras = [clave(v) for v in df.iloc[fila].tolist()]
            for formato, nombres in FORMATOS.items():
                if all(cabeceras.count(n) == 1 for n in nombres):
                    encontradas.append((hoja, fila, formato, cabeceras))
    if len(encontradas) != 1:
        raise ValueError(
            "No se identifica una única tabla de vuelos PACOTRON u OMS "
            f"(encontradas: {len(encontradas)}). Revisa las cabeceras."
        )
    return encontradas[0]


def _fecha(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip().replace("/", "-").replace(".", "-")
    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    return None


def _minutos(valor, formato: str) -> int | None:
    """Hora como 'HH:MM', objeto time, fracción de día de Excel o, en OMS, 'HHMM'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (datetime, time)):
        return valor.hour * 60 + valor.minute
    if isinstance(valor, (int, float)) and 0 <= valor < 1:
        return round(valor * 1440) % 1440
    texto = str(valor).strip()
    if m := re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)(:\d\d)?", texto):
        return int(m[1]) * 60 + int(m[2])
    if formato == "OMS" and re.fullmatch(r"\d{3,4}(\.0)?", texto):
        texto = texto.split(".")[0].zfill(4)
        h, m = int(texto[:2]), int(texto[2:])
        if h <= 23 and m <= 59:
            return h * 60 + m
    return None


def desfase_utc(dia: date, zona: str) -> int:
    """Minutos que hay que sumar a la hora Zulu para tener hora local ese día."""
    mediodia = datetime.combine(dia, time(12), tzinfo=timezone.utc)
    return int(mediodia.astimezone(ZoneInfo(zona)).utcoffset() / timedelta(minutes=1))


def _texto(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    return "" if texto in ("0", "-", "nan") else texto


def leer_vuelos(
    ruta: str | Path, dia: date, zona: str = "Europe/Madrid", horas_utc: bool = True
) -> tuple[list[Vuelo], list[Incidencia]]:
    ruta = Path(ruta)
    tablas = _leer_tablas(ruta)
    hoja, fila_cab, formato, cabeceras = _buscar_cabecera(tablas)
    df = tablas[hoja]
    columnas = {campo: cabeceras.index(nombre) for campo, nombre in zip(CAMPOS, FORMATOS[formato])}
    for campo, alias in OPCIONALES.items():
        columnas[campo] = next((cabeceras.index(a) for a in alias if a in cabeceras), None)

    desfase = desfase_utc(dia, zona) if horas_utc else 0
    vuelos, incidencias, vistos = [], [], set()
    for i in range(fila_cab + 1, len(df)):
        fila = df.iloc[i].tolist()
        ref = f"{hoja}!{i + 1}"
        valor = lambda campo: fila[columnas[campo]] if columnas.get(campo) is not None else None
        vuelo_in, vuelo_out = _texto(valor("VUELO_IN")), _texto(valor("VUELO_OUT"))
        if not vuelo_in and not vuelo_out:
            continue
        fecha = _fecha(valor("FECHA"))
        if fecha is None:
            if clave(valor("FECHA")) in (FORMATOS[formato][0], ""):
                continue
            incidencias.append(Incidencia("PENDIENTE", "VUELO_FECHA_INVALIDA",
                                          "Fecha de vuelo no interpretable; la fila no se incluye.", ref))
            continue
        if fecha != dia:
            continue

        vuelo = Vuelo(fecha=fecha, vuelo_in=vuelo_in, origen=_texto(valor("ORIGEN")),
                      vuelo_out=vuelo_out, destino=_texto(valor("DESTINO")),
                      tipo_avion=_texto(valor("TIPO")), puesto=_texto(valor("PUESTO")), fila_origen=ref)
        for campo in ("STA", "STD"):
            bruto = valor(campo)
            if _texto(bruto) == "":
                continue
            minutos = _minutos(bruto, formato)
            if minutos is None:
                incidencias.append(Incidencia("PENDIENTE", "VUELO_HORA_INVALIDA",
                                              f"Hora {campo} no interpretable ('{bruto}'); se deja vacía.", ref))
            else:
                setattr(vuelo, campo.lower(), minutos + desfase)
        if vuelo.vuelo_in and (not vuelo.origen or vuelo.sta is None):
            incidencias.append(Incidencia("AVISO", "VUELO_INCOMPLETO", "Llegada sin origen o STA.", ref))
        if vuelo.vuelo_out and (not vuelo.destino or vuelo.std is None):
            incidencias.append(Incidencia("AVISO", "VUELO_INCOMPLETO", "Salida sin destino o STD.", ref))
        if vuelo.sta is not None and vuelo.std is not None and vuelo.std < vuelo.sta:
            vuelo.std += 1440  # la salida es después de medianoche

        firma = (vuelo.vuelo_in, vuelo.origen, vuelo.sta, vuelo.vuelo_out, vuelo.destino, vuelo.std)
        if firma in vistos:
            incidencias.append(Incidencia("AVISO", "VUELO_DUPLICADO_ELIMINADO",
                                          "Fila idéntica a otra; se usa una sola vez.", ref))
            continue
        vistos.add(firma)
        vuelos.append(vuelo)

    if not vuelos:
        raise ValueError(f"No hay vuelos para el {dia:%d/%m/%Y} en {ruta.name}.")
    sin_hora = 10 ** 6  # filas sin horas válidas al final
    vuelos.sort(key=lambda v: v.sta if v.sta is not None else v.std if v.std is not None else sin_hora)
    return vuelos, incidencias
