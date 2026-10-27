"""Genera los datos de la empresa ficticia de la demo (todo inventado, sin datos reales).

- demo/cuadrante_octubre_2026.xlsx: cuadrante del mes de referencia, en el formato de la empresa
  (Depart. | Empleado | una columna por día con "HH:MM\\nHH:MM"). Vacaciones y bajas en color.
- demo/contratos.xlsx: Empleado | Contrato (TC, TP, FD, EVE, TCC).
- demo/vuelos_noviembre_2026.xlsx: programación del mes que se planifica (formato PACOTRON,
  horas Zulu). Inventada (vuelos XX), con la forma de una aerolínea vacacional británica: solo giros
  desde Reino Unido, sin aviones en base, y mucho más tráfico unos días que otros.
Sin nombres de personas: cada empleado es un código (EMP001…).
- demo/cuadrante_a_mano_noviembre_2026.xlsx: noviembre sin el programa (rotación con el horario de
  siempre), para compararlo con el que sale del programa.

    python ejemplos/generar_demo.py
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

SEMILLA = 2026
CARPETA = Path(__file__).parent / "demo"
REFERENCIA = (2026, 10)
PLANIFICADO = (2026, 11)
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

AEROLINEA = "XX"
AEROPUERTOS = ["MAN", "LBA", "BHX", "EMA", "STN", "GLA", "EDI", "BFS", "NCL", "BRS", "LPL", "BOH"]
# Giros por día de la semana (lunes a domingo): una vacacional concentra el tráfico en unos días.
GIROS_POR_DIA = [26, 20, 24, 32, 28, 36, 34]

# Función del cuadrante -> (personas, proporción de tiempo completo). Unas 130 personas.
PLANTILLA = {"TL": (27, 0.5), "TOW/JAR": (13, 0.45), "PB*/JAR": (10, 0.45), "PB": (4, 0.5),
             "PCP": (56, 0.3), "GHA": (6, 0.3), "JAR": (8, 0.4)}
MANDOS = {"RCO": 4, "ARCO": 4}
VACACIONES = "FFFFFF00"
BAJA = "FF7030A0"


def dias_del_mes(anio: int, mes: int) -> list[date]:
    d = date(anio, mes, 1)
    dias = []
    while d.month == mes:
        dias.append(d)
        d += timedelta(days=1)
    return dias


def hhmm(minutos: int) -> str:
    return f"{minutos // 60 % 24:02d}:{minutos % 60:02d}"


def texto(tramos: list[tuple[int, int]]) -> str:
    return "\n\n".join(f"{hhmm(i)}\n{hhmm(f)}" for i, f in tramos)


def personas(rnd: random.Random) -> list[dict]:
    """Cada persona: función, contrato, grupo de rotación y horario habitual de mañana y de tarde."""
    resultado = []
    for funcion, (n, completos) in PLANTILLA.items():
        for i in range(n):
            completo = i < round(n * completos)
            contrato = ("TCC" if rnd.random() < 0.03 else "TC") if completo else rnd.choices(
                ["TP", "FD", "EVE"], [0.85, 0.1, 0.05])[0]
            if completo:
                manana = [(m := rnd.choice(range(240, 421, 15)), m + 480)]
                tarde = [(t := rnd.choice(range(720, 961, 15)), t + 480)]
            else:
                horas = rnd.choice([4, 5, 5, 6, 6, 7]) * 60
                if rnd.random() < 0.2:      # partido: dos tramos de al menos 2 h con pausa de 1 a 5 h
                    a = rnd.choice(range(270, 421, 15))
                    pausa = rnd.choice([120, 180, 240])
                    primero = horas // 2 // 15 * 15
                    manana = [(a, a + primero), (a + primero + pausa, a + horas + pausa)]
                else:
                    manana = [(m := rnd.choice(range(270, 541, 15)), m + horas)]
                tarde = [(t := rnd.choice(range(840, 1141, 15)), min(t + horas, 1440))]
            resultado.append({"funcion": funcion, "contrato": contrato, "grupo": i % 3,
                              "manana": manana, "tarde": tarde})
    for funcion, n in MANDOS.items():
        for i in range(n):
            resultado.append({"funcion": funcion, "contrato": "TC", "grupo": i % 4, "mando": True,
                              "manana": [(285, 885)], "tarde": [(900, 1440)]})
    rnd.shuffle(resultado)
    resultado.sort(key=lambda p: list(PLANTILLA).index(p["funcion"]) if p["funcion"] in PLANTILLA else 99)
    for n, p in enumerate(resultado, 1):
        p["nombre"] = f"EMP{n:03d}"
    return resultado


def jornada(p: dict, dia: date) -> list[tuple[int, int]] | None:
    """Rotación 6x3 (MMMTTT + 3 libres) o 4x4 para mandos (MMTT + 4 libres). Continúa entre meses."""
    if p.get("mando"):
        pos = ((dia - date(2026, 1, 5)).days + 2 * p["grupo"]) % 8
        return None if pos >= 4 else (p["manana"] if pos < 2 else p["tarde"])
    pos = ((dia - date(2026, 1, 5)).days + 3 * p["grupo"]) % 9
    return None if pos >= 6 else (p["manana"] if pos < 3 else p["tarde"])


def escribir_cuadrante(gente: list[dict], dias: list[date], ruta: Path, rnd: random.Random) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cuadrante"
    ws.append(["Depart.", "Empleado"] + [f"{d.day}.{d.month}\n{DIAS_SEMANA[d.weekday()]}" for d in dias])
    for p in gente:
        # Unas vacaciones (1 de cada 10) o una baja (1 de cada 40) en el mes.
        ausencia, color = set(), None
        if rnd.random() < 0.1:
            inicio = rnd.randrange(len(dias) - 9)
            ausencia, color = set(dias[inicio:inicio + 9]), VACACIONES
        elif rnd.random() < 0.03:
            inicio = rnd.randrange(len(dias) - 5)
            ausencia, color = set(dias[inicio:inicio + rnd.randint(3, 6)]), BAJA
        ws.append([p["funcion"], p["nombre"]] + [
            None if d in ausencia or not (j := jornada(p, d)) else texto(j) for d in dias])
        for d, celda in zip(dias, ws[ws.max_row][2:]):
            if d in ausencia:
                celda.fill = PatternFill("solid", fgColor=color)
            celda.alignment = Alignment(wrap_text=True, horizontal="center")
    for celda in ws[1]:
        celda.font = Font(bold=True)
        celda.alignment = Alignment(wrap_text=True, horizontal="center")
    ws.column_dimensions["B"].width = 12
    ws.freeze_panes = "C2"
    wb.save(ruta)


def escribir_contratos(gente: list[dict], ruta: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Contratos"
    ws.append(["Empleado", "Contrato"])
    for p in gente:
        ws.append([p["nombre"], p["contrato"]])
    wb.save(ruta)


def vuelos_del_dia(dia: date, rnd: random.Random) -> list[tuple]:
    """(vuelo_in, origen, sta, vuelo_out, destino, std, tipo, puesto) en hora local.
    Solo giros desde Reino Unido (ningún avión duerme en la base), de 50 a 60 minutos, en tres olas:
    mañana, primera hora de la tarde y noche."""
    filas = []
    giros = GIROS_POR_DIA[dia.weekday()] + rnd.randint(-2, 2)

    def numero() -> str:
        return f"{AEROLINEA}{rnd.randint(100, 2999)}"

    for _ in range(giros):
        ola = rnd.choices([(450, 750), (750, 1080), (1080, 1380)], [0.45, 0.35, 0.2])[0]
        sta = rnd.choice(range(ola[0], ola[1], 5))
        origen = rnd.choice(AEROPUERTOS)
        puesto = f"R{rnd.randint(1, 15):02d}" if rnd.random() < 0.3 else f"C{rnd.randint(1, 20):02d}"
        filas.append((numero(), origen, sta, numero(), origen, sta + rnd.choice([50, 55, 55, 60]),
                      rnd.choice(["B738", "B738", "A21N"]), puesto))
    return sorted(filas, key=lambda f: f[2])


def escribir_vuelos(dias: list[date], ruta: Path, rnd: random.Random) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Vuelos"
    ws.append(["FLIGHT DATE.", "FLIGHT IN", "ORIG", "STA", "FLIGHT OUT", "DEST", "STD", "AC TYPE", "STAND"])
    zulu = 60       # noviembre: Madrid es UTC+1; los archivos de vuelos van en hora Zulu
    for d in dias:
        for vin, orig, sta, vout, dest, std, tipo, stand in vuelos_del_dia(d, rnd):
            ws.append([d.strftime("%d/%m/%Y"), vin, orig, None if sta is None else hhmm(sta - zulu),
                       vout, dest, None if std is None else hhmm(std - zulu), tipo, stand])
    wb.save(ruta)


def main() -> None:
    rnd = random.Random(SEMILLA)
    CARPETA.mkdir(exist_ok=True)
    gente = personas(rnd)
    escribir_cuadrante(gente, dias_del_mes(*REFERENCIA), CARPETA / "cuadrante_octubre_2026.xlsx", rnd)
    escribir_contratos(gente, CARPETA / "contratos.xlsx")
    escribir_vuelos(dias_del_mes(*PLANIFICADO), CARPETA / "vuelos_noviembre_2026.xlsx", rnd)
    # Para comparar: noviembre "a mano", siguiendo la rotación con el horario de siempre de cada uno.
    escribir_cuadrante(gente, dias_del_mes(*PLANIFICADO), CARPETA / "cuadrante_a_mano_noviembre_2026.xlsx", rnd)
    print(f"{len(gente)} personas en {CARPETA}")


if __name__ == "__main__":
    main()
