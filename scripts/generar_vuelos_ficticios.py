"""Genera una programación de vuelos ficticia en formato PACOTRON (horas Zulu), estilo base low cost.

Uso: python scripts/generar_vuelos_ficticios.py [--desde 2027-07-12] [--dias 7] [--aviones 12] [--visitantes 30]
"""
import argparse
import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

DESTINOS = ["STN", "BGY", "CRL", "DUB", "MAN", "EDI", "BVA", "CIA", "HHN", "NRN", "BRS", "LPL", "EMA",
            "WMI", "BUD", "OPO", "FCO", "BLQ", "PMO", "MRS", "TSF", "SXF", "VIE", "KRK", "LIS"]
TIPOS = ["B738", "B738", "B738", "B38M"]


def zulu(dia: date, minutos_locales: int, zona: str) -> tuple[date, str]:
    local = datetime.combine(dia, time(0), tzinfo=ZoneInfo(zona)) + timedelta(minutes=minutos_locales)
    utc = local.astimezone(timezone.utc)
    return utc.date(), utc.strftime("%H:%M")


def generar_dia(dia: date, aviones: int, visitantes: int, zona: str, numeros: iter) -> list[dict]:
    filas = []

    def fila(llegada=None, salida=None):
        """llegada / salida: (minutos locales, aeropuerto)."""
        remoto = random.random() < 0.3
        f = {"FLIGHT DATE.": dia.strftime("%d/%m/%Y"), "FLIGHT IN": "", "ORIG": "", "STA": "",
             "FLIGHT OUT": "", "DEST": "", "STD": "", "AC TYPE": random.choice(TIPOS),
             "STAND": f"R{random.randint(1, 15):02d}" if remoto else f"C{random.randint(1, 20):02d}"}
        if llegada:
            f["FLIGHT IN"], f["ORIG"], f["STA"] = f"FR{next(numeros)}", llegada[1], zulu(dia, llegada[0], zona)[1]
        if salida:
            f["FLIGHT OUT"], f["DEST"], f["STD"] = f"FR{next(numeros)}", salida[1], zulu(dia, salida[0], zona)[1]
        filas.append(f)

    # Aviones basados: primera ola de salidas, rotaciones con giros de 25 min y pernocta.
    for i in range(aviones):
        hora = 6 * 60 + 5 * i + random.choice([0, 0, 5, 10])
        destino = random.choice(DESTINOS)
        fila(salida=(hora, destino))
        for _ in range(random.choice([2, 3, 3])):
            bloque = random.randint(90, 165)
            llegada = hora + 2 * bloque + 25
            if llegada > 23 * 60:
                break
            siguiente = random.choice(DESTINOS)
            if llegada + 25 + 2 * bloque + 25 > 24 * 60:
                fila(llegada=(llegada, destino))
                break
            fila(llegada=(llegada, destino), salida=(llegada + 25, siguiente))
            hora, destino = llegada + 25, siguiente
        else:
            fila(llegada=(hora + 2 * random.randint(90, 165) + 25, destino))

    # Aviones de otras bases: giros sueltos durante el día.
    for _ in range(visitantes):
        llegada = random.randint(8 * 60, 22 * 60)
        fila(llegada=(llegada, random.choice(DESTINOS)), salida=(llegada + random.choice([25, 25, 30, 35]),
                                                                 random.choice(DESTINOS)))
    return filas


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--desde", type=date.fromisoformat, default=date(2027, 7, 12))
    p.add_argument("--dias", type=int, default=7)
    p.add_argument("--aviones", type=int, default=12, help="Aviones basados que pernoctan")
    p.add_argument("--visitantes", type=int, default=30, help="Giros de aviones de otras bases por día")
    p.add_argument("--zona", default="Europe/Madrid")
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--salida", default="ejemplos/vuelos_ficticios.xlsx")
    args = p.parse_args()

    random.seed(args.semilla)
    numeros = iter(random.sample(range(1000, 9999), 5000))
    filas = []
    for d in range(args.dias):
        filas += generar_dia(args.desde + timedelta(days=d), args.aviones, args.visitantes, args.zona, numeros)
    df = pd.DataFrame(filas)
    df.to_excel(args.salida, index=False, sheet_name="Vuelos")
    print(f"{len(df)} filas de programación en {args.salida} (horas Zulu)")


if __name__ == "__main__":
    main()
