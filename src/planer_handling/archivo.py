"""Lo que se sube una vez y se guarda en este ordenador, por meses: el cuadrante real, el que hace el
programa (con los retoques a mano) y los vuelos. Solo con códigos de persona, nunca nombres (ver
anonimizar)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .importar.cuadrante import FilaCuadrante, Jornada, tramos
from .mensual import CuadranteMes, dias_del_mes
from .modelos import Vuelo, hhmm

TIPOS = {"real": "Cuadrante real", "programa": "Cuadrante del programa"}


def texto_celda(jornada: Jornada | None, marca_vacia: str = "", motivos: dict[str, str] | None = None) -> str:
    """"06:00-14:00", "06:00-10:00 / 15:00-19:00", el motivo de una ausencia o vacío."""
    motivo = (motivos or {}).get((jornada.marca if jornada else "") or marca_vacia, "")
    horas = " / ".join(f"{hhmm(i)}-{hhmm(f)}" for i, f in jornada.tramos) if jornada else ""
    return f"{motivo} {horas}".strip() if motivo else horas


HORA_SUELTA = re.compile(r"(?<![\d:])(\d{1,2})(?:[:.h]?([0-5]\d))?(?![\d:])")


def leer_celda(texto: str, colores: dict[str, str]) -> tuple[list[tuple[int, int]], str]:
    """Lo contrario de texto_celda: tramos y color de la marca (si empieza por un motivo). Vale
    "06:00-14:00", "6-14", "0600-1400" y el partido "6-10 / 15-19"."""
    texto = (texto or "").strip()
    marca = ""
    for motivo, color in sorted(colores.items(), key=lambda x: -len(x[0])):
        if texto.lower().startswith(motivo.lower()):
            marca, texto = color, texto[len(motivo):]
            break
    horas = [(int(h), int(m or 0)) for h, m in HORA_SUELTA.findall(texto)]
    if any(h > 23 for h, _ in horas) or len(horas) % 2 or re.search(r"[^\s\-/–:.,]", HORA_SUELTA.sub("", texto)):
        raise ValueError(texto)
    return tramos(" ".join(f"{h:02d}:{m:02d}" for h, m in horas)), marca


class Archivo:
    def __init__(self, carpeta: str | Path):
        self.carpeta = Path(carpeta)

    def _mes(self, anio: int, mes: int) -> Path:
        return self.carpeta / f"{anio}-{mes:02d}"

    # --- cuadrantes ---
    def guardar_cuadrante(self, anio: int, mes: int, filas: list[FilaCuadrante], tipo: str = "real") -> None:
        carpeta = self._mes(anio, mes)
        carpeta.mkdir(parents=True, exist_ok=True)
        datos = [{"funcion": f.funcion, "codigo": f.nombre,
                  "jornadas": {d.isoformat(): [j.tramos, j.marca] for d, j in sorted(f.jornadas.items())},
                  "marcas_vacias": {d.isoformat(): m for d, m in sorted(f.marcas_vacias.items())}} for f in filas]
        (carpeta / f"cuadrante_{tipo}.json").write_text(json.dumps(datos), encoding="utf-8")

    def cuadrante(self, anio: int, mes: int, tipo: str = "real") -> list[FilaCuadrante] | None:
        ruta = self._mes(anio, mes) / f"cuadrante_{tipo}.json"
        if not ruta.exists():
            return None
        filas = []
        for n, x in enumerate(json.loads(ruta.read_text(encoding="utf-8")), 2):
            f = FilaCuadrante(x["funcion"], x["codigo"], n)
            f.jornadas = {date.fromisoformat(d): Jornada([tuple(t) for t in tr], m) for d, (tr, m) in x["jornadas"].items()}
            f.marcas_vacias = {date.fromisoformat(d): m for d, m in x["marcas_vacias"].items()}
            filas.append(f)
        return filas

    # --- vuelos ---
    def guardar_vuelos(self, anio: int, mes: int, vuelos: dict[date, list[Vuelo]]) -> None:
        carpeta = self._mes(anio, mes)
        carpeta.mkdir(parents=True, exist_ok=True)
        datos = {d.isoformat(): [{**asdict(v), "fecha": v.fecha.isoformat()} for v in lista]
                 for d, lista in sorted(vuelos.items())}
        (carpeta / "vuelos.json").write_text(json.dumps(datos), encoding="utf-8")

    def vuelos(self, anio: int, mes: int) -> dict[date, list[Vuelo]] | None:
        ruta = self._mes(anio, mes) / "vuelos.json"
        if not ruta.exists():
            return None
        return {date.fromisoformat(d): [Vuelo(**{**v, "fecha": date.fromisoformat(v["fecha"])}) for v in lista]
                for d, lista in json.loads(ruta.read_text(encoding="utf-8")).items()}

    # --- datos de la plantilla que no van por meses ---
    def guardar_contratos(self, contratos: dict[str, str]) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        (self.carpeta / "contratos.json").write_text(json.dumps(contratos), encoding="utf-8")

    def contratos(self) -> dict[str, str] | None:
        ruta = self.carpeta / "contratos.json"
        return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None

    def guardar_formacion(self, fichas: dict) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        datos = {k: {"contrato": f.contrato, "da": sorted(f.da), "quita": sorted(f.quita)} for k, f in fichas.items()}
        (self.carpeta / "formacion.json").write_text(json.dumps(datos), encoding="utf-8")

    def formacion(self) -> dict | None:
        from .importar.habilitaciones import Ficha
        ruta = self.carpeta / "formacion.json"
        if not ruta.exists():
            return None
        return {k: Ficha(x["contrato"], set(x["da"]), set(x["quita"]))
                for k, x in json.loads(ruta.read_text(encoding="utf-8")).items()}

    def meses(self) -> list[tuple[int, int, set[str]]]:
        """(año, mes, qué hay guardado: real, programa, vuelos) de cada mes con algo, del más reciente."""
        if not self.carpeta.exists():
            return []
        resultado = []
        for c in sorted(self.carpeta.iterdir(), reverse=True):
            if c.is_dir() and len(c.name) == 7 and c.name[4] == "-":
                hay = {t for t in TIPOS if (c / f"cuadrante_{t}.json").exists()}
                if (c / "vuelos.json").exists():
                    hay.add("vuelos")
                if hay:
                    resultado.append((int(c.name[:4]), int(c.name[5:]), hay))
        return resultado


def filas_desde_plan(cm: CuadranteMes, colores: dict[str, str]) -> list[FilaCuadrante]:
    """El cuadrante que sale del programa, como filas de cuadrante (las ausencias con su color)."""
    filas = {p.empleado.id: FilaCuadrante(p.funcion, p.empleado.nombre or p.empleado.id, n)
             for n, p in enumerate(cm.perfiles, 2)}
    for dp in cm.dias:
        for j in dp.jornadas:
            filas[j.perfil.empleado.id].jornadas[dp.dia] = Jornada(list(j.tramos))
        for id_, motivo in dp.ausentes.items():
            if id_ in filas and motivo in colores:
                filas[id_].marcas_vacias[dp.dia] = colores[motivo]
    return list(filas.values())


def tabla(filas: list[FilaCuadrante], dias: list[date], colores: dict[str, str]) -> list[dict]:
    """Una fila por persona y una columna por día, para verlo y editarlo en pantalla."""
    motivos = {c: m for m, c in colores.items()}
    return [{"Código": f.nombre, "Función": f.funcion,
             **{f"{d.day:02d}": texto_celda(f.jornadas.get(d), f.marcas_vacias.get(d, ""), motivos) for d in dias}}
            for f in filas]


def desde_tabla(registros: list[dict], dias: list[date], colores: dict[str, str],
                errores: list[str] | None = None) -> list[FilaCuadrante]:
    """`errores`: si se pasa, se apuntan las celdas que no se entienden (y se dejan como libre)."""
    filas = []
    for n, r in enumerate(registros, 2):
        if not str(r.get("Código") or "").strip():
            continue
        f = FilaCuadrante(str(r.get("Función") or "").strip().upper(), str(r["Código"]).strip(), n)
        for d in dias:
            celda = r.get(f"{d.day:02d}")
            celda = "" if celda is None or str(celda) == "nan" else str(celda)
            try:
                t, marca = leer_celda(celda, colores)
            except ValueError:
                if errores is not None:
                    errores.append(f"{f.nombre} día {d.day}: «{celda}»")
                continue
            if t:
                f.jornadas[d] = Jornada(t, marca)
            elif marca:
                f.marcas_vacias[d] = marca
        filas.append(f)
    return filas


def exportar_cuadrante(filas: list[FilaCuadrante], anio: int, mes: int, ruta: str | Path,
                       colores: dict[str, str]) -> Path:
    """Excel con el mismo formato que se lee (EMPLEADO, DEPART. y un día por columna): se puede volver
    a subir. Las ausencias van con su color."""
    dias = dias_del_mes(anio, mes)
    wb = Workbook()
    ws = wb.active
    ws.title = f"{anio}-{mes:02d}"
    ws.append(["DEPART.", "EMPLEADO"] + [d for d in dias])
    for c in ws[1]:
        c.font = Font(bold=True)
    for c in ws[1][2:]:
        c.number_format = "DD/MM"
    for f in filas:
        ws.append([f.funcion, f.nombre] + [
            "\n".join(f"{hhmm(i)}\n{hhmm(fin)}" for i, fin in f.jornadas[d].tramos) if d in f.jornadas else None
            for d in dias])
        for k, d in enumerate(dias, 3):
            marca = (f.jornadas[d].marca if d in f.jornadas else "") or f.marcas_vacias.get(d, "")
            if marca:
                ws.cell(ws.max_row, k).fill = PatternFill("solid", fgColor=marca)
            ws.cell(ws.max_row, k).alignment = Alignment(wrap_text=True, horizontal="center")
    ws.freeze_panes = "C2"
    ws.column_dimensions["B"].width = 12
    wb.save(ruta)
    return Path(ruta)


def _hora(minutos: int | None) -> str:
    """"01:30+1" si es del día siguiente."""
    return "" if minutos is None else hhmm(minutos) + ("+1" if minutos >= 1440 else "")


def tabla_vuelos(vuelos: list[Vuelo]) -> list[dict]:
    """Los vuelos de un día, para verlos y corregirlos en pantalla."""
    return [{"Llegada": v.vuelo_in, "Origen": v.origen, "STA": _hora(v.sta),
             "Salida": v.vuelo_out, "Destino": v.destino, "STD": _hora(v.std),
             "Avión": v.tipo_avion, "Puesto": v.puesto} for v in vuelos]


def _minutos(texto) -> int | None:
    texto = str(texto or "").strip().replace(".", ":").replace("h", ":")
    if not texto or texto.lower() == "nan":
        return None
    if texto.endswith("+1"):
        return _minutos(texto[:-2]) + 1440
    if ":" not in texto and texto.isdigit():
        texto = f"{texto[:-2] or 0}:{texto[-2:]}"
    h, m = texto.split(":")[:2]
    return int(h) * 60 + int(m)


def desde_tabla_vuelos(registros: list[dict], dia: date) -> list[Vuelo]:
    vuelos = []
    for n, r in enumerate(registros, 1):
        texto = lambda c: "" if r.get(c) is None or str(r.get(c)) == "nan" else str(r.get(c)).strip()
        if not (texto("Llegada") or texto("Salida")):
            continue
        vuelos.append(Vuelo(dia, texto("Llegada").upper(), texto("Origen").upper(), _minutos(r.get("STA")),
                            texto("Salida").upper(), texto("Destino").upper(), _minutos(r.get("STD")),
                            texto("Avión"), texto("Puesto").upper(), f"pantalla {n}"))
    return vuelos
