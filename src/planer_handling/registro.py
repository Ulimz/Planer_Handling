"""Registro de plantilla y ausencias que se lleva desde la web.

Se guarda en dos CSV dentro de la carpeta de datos del ordenador donde se usa (nunca en el
repositorio): plantilla.csv (empleado, función) y ausencias.csv (una fila por ausencia).
Una ausencia sin fecha de fin sigue abierta hasta que se da el alta.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .configuracion import Configuracion
from .importar.cuadrante import FilaCuadrante
from .mensual import Ausencia

CAMPOS = ["id", "empleado", "funcion", "motivo", "desde", "hasta", "nota"]


@dataclass
class Registro:
    id: str
    empleado: str
    funcion: str
    motivo: str
    desde: date
    hasta: date | None = None           # None: abierta hasta el alta
    nota: str = ""

    @property
    def abierta(self) -> bool:
        return self.hasta is None

    def activa(self, dia: date) -> bool:
        return self.desde <= dia and (self.hasta is None or dia <= self.hasta)

    def como_ausencia(self) -> Ausencia:
        return Ausencia(self.empleado, self.desde, self.hasta or date.max, self.motivo)


def motivos(conf: Configuracion) -> dict[str, str]:
    """Motivo de ausencia -> color de celda, según la tabla de colores de la empresa."""
    resultado = {m["motivo"]: rgb for rgb, m in conf.datos.get("marcas", {}).items() if not m["disponible"]}
    resultado.update(conf.datos.get("motivos_extra", {}))
    return resultado


class Almacen:
    def __init__(self, carpeta: str | Path):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta_ausencias = self.carpeta / "ausencias.csv"
        self.ruta_plantilla = self.carpeta / "plantilla.csv"

    # --- plantilla ---
    def guardar_plantilla(self, filas: list[FilaCuadrante]) -> int:
        personas = sorted({(f.nombre.strip(), f.funcion.strip()) for f in filas if f.nombre.strip()})
        with self.ruta_plantilla.open("w", newline="", encoding="utf-8") as fh:
            escritor = csv.writer(fh)
            escritor.writerow(["empleado", "funcion"])
            escritor.writerows(personas)
        return len(personas)

    def plantilla(self) -> list[tuple[str, str]]:
        if not self.ruta_plantilla.exists():
            return []
        with self.ruta_plantilla.open(encoding="utf-8") as fh:
            return [(f["empleado"], f["funcion"]) for f in csv.DictReader(fh)]

    # --- ausencias ---
    def registros(self) -> list[Registro]:
        if not self.ruta_ausencias.exists():
            return []
        with self.ruta_ausencias.open(encoding="utf-8") as fh:
            return [Registro(f["id"], f["empleado"], f["funcion"], f["motivo"], date.fromisoformat(f["desde"]),
                             date.fromisoformat(f["hasta"]) if f["hasta"] else None, f["nota"])
                    for f in csv.DictReader(fh)]

    def _escribir(self, registros: list[Registro]) -> None:
        temporal = self.ruta_ausencias.with_suffix(".tmp")
        with temporal.open("w", newline="", encoding="utf-8") as fh:
            escritor = csv.DictWriter(fh, CAMPOS)
            escritor.writeheader()
            for r in registros:
                fila = asdict(r)
                fila["desde"] = r.desde.isoformat()
                fila["hasta"] = r.hasta.isoformat() if r.hasta else ""
                escritor.writerow(fila)
        temporal.replace(self.ruta_ausencias)

    def anadir(self, empleado: str, funcion: str, motivo: str, desde: date, hasta: date | None = None,
               nota: str = "") -> Registro:
        if hasta and hasta < desde:
            raise ValueError("La fecha de fin es anterior a la de inicio.")
        registro = Registro(uuid.uuid4().hex[:8], empleado, funcion, motivo, desde, hasta, nota)
        existentes = self.registros()
        for r in existentes:
            if r.empleado == empleado and r.desde <= (hasta or date.max) and desde <= (r.hasta or date.max):
                raise ValueError(f"{empleado} ya tiene apuntado {r.motivo.lower()} desde el {r.desde:%d/%m/%Y}"
                                 + (f" hasta el {r.hasta:%d/%m/%Y}." if r.hasta else " sin fecha de fin."))
        self._escribir(existentes + [registro])
        return registro

    def dar_alta(self, id_registro: str, dia_alta: date) -> None:
        """El día del alta la persona ya trabaja: la ausencia acaba el día anterior."""
        registros = self.registros()
        for r in registros:
            if r.id == id_registro:
                if dia_alta <= r.desde:
                    raise ValueError("El alta no puede ser antes del inicio de la ausencia.")
                r.hasta = date.fromordinal(dia_alta.toordinal() - 1)
        self._escribir(registros)

    def borrar(self, id_registro: str) -> None:
        self._escribir([r for r in self.registros() if r.id != id_registro])

    def ausencias(self) -> list[Ausencia]:
        return [r.como_ausencia() for r in self.registros()]
