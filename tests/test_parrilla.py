import subprocess
import sys
from datetime import date

import pandas as pd

from planer_handling.importar.plantilla import leer_plantilla
from planer_handling.importar.vuelos import leer_vuelos
from planer_handling.parrilla_excel import exportar
from planer_handling.planificador import generar_parrilla

from .conftest import RAIZ


def test_parrilla_de_un_dia_con_datos_ficticios(tmp_path, conf):
    vuelos_x = tmp_path / "vuelos.xlsx"
    plantilla_x = tmp_path / "plantilla.xlsx"
    subprocess.run([sys.executable, RAIZ / "scripts" / "generar_vuelos_ficticios.py", "--dias", "1",
                    "--salida", vuelos_x], check=True, capture_output=True)
    subprocess.run([sys.executable, RAIZ / "scripts" / "generar_plantilla_ficticia.py", "--escala", "2",
                    "--salida", plantilla_x], check=True, capture_output=True)
    dia = date(2027, 7, 12)
    vuelos, incidencias = leer_vuelos(vuelos_x, dia)
    parrilla = generar_parrilla(dia, vuelos, leer_plantilla(plantilla_x), conf, incidencias, segundos=10)

    # Nadie aparece dos veces y ningún equipo tiene vuelos solapados
    codigos = {i.codigo for i in parrilla.incidencias}
    assert "EMPLEADO_DUPLICADO" not in codigos
    assert "VUELOS_SOLAPADOS" not in codigos
    assert "TRAMO_FUERA_TURNO" not in codigos
    asignadas = sum(1 for t in parrilla.tareas if t.id in parrilla.asignadas)
    assert asignadas >= len(parrilla.tareas) - 2

    salida = exportar(parrilla, tmp_path / "parrilla.xlsx", conf.equipo_plataforma)
    hojas = pd.read_excel(salida, sheet_name=None)
    assert {"Resumen", "Equipos", "Vuelos", "Jardineras", "Personal", "Incidencias", "Gantt"} <= set(hojas)
    assert len(hojas["Equipos"]) == len(parrilla.reparto.equipos)


def test_parrilla_real_medianoche_y_filas_invertidas(tmp_path):
    from datetime import time
    from openpyxl import Workbook
    from planer_handling.importar.parrilla_real import leer_vuelos_parrilla
    ruta = tmp_path / "parrilla.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "01-10"
    # Cabecera con ORIG. y PK borrados, como llegan algunas hojas reales.
    ws.append(["", "N.Vuelo", "", "Dest.", "N.Vuelo", "", "Matricula", "", "", "ETA", "STA", "STD", "Grupo"])
    ws.append(["STN", "FR", "1", "DUB", "FR", "2", "", "", "10", None, time(9, 0), time(8, 15), "M1"])
    ws.append(["MAN", "FR", "3", None, None, None, "", "", "20", None, time(0, 30), None, "T9"])
    wb.save(ruta)
    vuelos, grupos = leer_vuelos_parrilla(ruta, "01-10", date(2026, 10, 1))
    assert [(v.codigo, v.sta, v.std) for v in vuelos] == [("FR1", 540, None), ("FR2", None, 495), ("FR3", 1470, None)]
    assert grupos["FR2"] == "M1" and vuelos[0].puesto == "10"
