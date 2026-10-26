"""Excel del cuadrante mensual: mismo formato que el cuadrante de la empresa (se puede volver a
leer con el modo --cuadrante) más hojas de cobertura y de horas por persona."""
from __future__ import annotations

from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .mensual import INICIO_MAS_TEMPRANO, PASO, CuadranteMes, texto_jornada
from .modelos import hhmm

DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
NEGRITA = Font(bold=True)
CABECERA = PatternFill("solid", fgColor="FFD9E1F2")
FALTA = PatternFill("solid", fgColor="FFF8CBAD")
AUSENTE = PatternFill("solid", fgColor="FFD9D9D9")


def exportar_mes(cm: CuadranteMes, ruta, con_nombres: bool = False) -> None:
    wb = Workbook()
    _hoja_cuadrante(wb.active, cm, con_nombres)
    _hoja_cobertura(wb.create_sheet("Cobertura"), cm)
    _hoja_horas(wb.create_sheet("Horas"), cm)
    _hoja_curva(wb.create_sheet("Curva"), cm)
    wb.save(ruta)


def _hoja_cuadrante(ws, cm: CuadranteMes, con_nombres: bool) -> None:
    ws.title = "Cuadrante"
    dias = [d.dia for d in cm.dias]
    ws.append(["Depart.", "Empleado", "Patrón"] + [f"{d.day}.{d.month}\n{DIAS_SEMANA[d.weekday()]}" for d in dias])
    por_persona = defaultdict(dict)
    for dp in cm.dias:
        for j in dp.jornadas:
            por_persona[j.perfil.empleado.id][dp.dia] = j
    for p in cm.perfiles:
        e = p.empleado
        nombre = e.nombre if con_nombres else e.id
        fila = [p.funcion, nombre, p.patron]
        for dp in cm.dias:
            j = por_persona[e.id].get(dp.dia)
            fila.append(texto_jornada(j.tramos) if j else dp.ausentes.get(e.id))
        ws.append(fila)
        for dp, celda in zip(cm.dias, ws[ws.max_row][3:]):
            if e.id in dp.ausentes:
                celda.fill = AUSENTE
    for celda in ws[1]:
        celda.font, celda.fill = NEGRITA, CABECERA
        celda.alignment = Alignment(wrap_text=True, horizontal="center")
    for col in range(4, 4 + len(dias)):
        ws.column_dimensions[get_column_letter(col)].width = 7
    for fila in ws.iter_rows(min_row=2, min_col=4):
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, horizontal="center")
    ws.freeze_panes = "D2"


def _hoja_cobertura(ws, cm: CuadranteMes) -> None:
    ws.append(["Día", "Vuelos", "Pico de equipos", "Personas", "Horas planificadas",
               "Horas sin cubrir TL", "Horas sin cubrir PB/TOW", "Horas sin cubrir operarios"])
    for dp in cm.dias:
        fila = [dp.dia, dp.vuelos, max(dp.demanda["TL"]), len(dp.jornadas),
                round(sum(j.minutos for j in dp.jornadas) / 60, 1)]
        fila += [round(dp.deficit(r) / 60, 1) for r in ("TL", "PB/TOW", "Operario")]
        ws.append(fila)
        if any(v > 0 for v in fila[5:]):
            for celda in ws[ws.max_row][5:]:
                celda.fill = FALTA
    for celda in ws[1]:
        celda.font, celda.fill = NEGRITA, CABECERA
    ws.column_dimensions["A"].width = 12


def _hoja_horas(ws, cm: CuadranteMes) -> None:
    ws.append(["Empleado", "Función", "Patrón", "Días mes anterior", "Horas mes anterior", "Días planificados",
               "Horas planificadas"])
    dias, minutos = defaultdict(int), defaultdict(int)
    for dp in cm.dias:
        for j in dp.jornadas:
            dias[j.perfil.empleado.id] += 1
            minutos[j.perfil.empleado.id] += j.minutos
    for p in cm.perfiles:
        e = p.empleado
        ws.append([e.id, p.funcion, p.patron, p.dias_referencia, round(p.minutos_referencia / 60, 1),
                   dias[e.id], round(minutos[e.id] / 60, 1)])
    for celda in ws[1]:
        celda.font, celda.fill = NEGRITA, CABECERA


def _hoja_curva(ws, cm: CuadranteMes) -> None:
    """Demanda frente a cobertura cada 15 minutos, para hacer gráficos."""
    ws.append(["Día", "Hora", "Rol", "Necesarios", "Planificados"])
    for dp in cm.dias:
        for rol in ("TL", "PB/TOW", "Operario"):
            for k, (d, c) in enumerate(zip(dp.demanda[rol], dp.cobertura[rol])):
                if d or c:
                    ws.append([dp.dia, hhmm(INICIO_MAS_TEMPRANO + k * PASO), rol, d, c])
    for celda in ws[1]:
        celda.font, celda.fill = NEGRITA, CABECERA
