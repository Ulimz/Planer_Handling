"""Uso: planer --fecha 2027-07-15 --vuelos vuelos.xlsx --plantilla plantilla.xlsx [--config config/base.yaml]"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .configuracion import Configuracion
from .importar.plantilla import leer_plantilla
from .importar.vuelos import leer_vuelos
from .parrilla_excel import exportar
from .planificador import generar_parrilla


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Genera la parrilla diaria de una base de handling.")
    p.add_argument("--fecha", required=True, type=date.fromisoformat, help="Día a planificar (AAAA-MM-DD)")
    p.add_argument("--vuelos", required=True, help="Programación en formato PACOTRON u OMS (.xlsx o .csv)")
    p.add_argument("--plantilla", required=True, help="Excel con hojas Plantilla y Habilitaciones")
    p.add_argument("--config", default="config/base.yaml")
    p.add_argument("--salida", help="Excel de salida (por defecto salida/parrilla_AAAA-MM-DD.xlsx)")
    p.add_argument("--horas-locales", action="store_true", help="Las horas del archivo ya son locales, no Zulu")
    p.add_argument("--segundos", type=float, default=30, help="Tiempo máximo del optimizador por asignación")
    args = p.parse_args(argv)

    conf = Configuracion.cargar(args.config)
    vuelos, incidencias = leer_vuelos(args.vuelos, args.fecha, conf.zona_horaria, horas_utc=not args.horas_locales)
    plantilla = leer_plantilla(args.plantilla)
    parrilla = generar_parrilla(args.fecha, vuelos, plantilla, conf, incidencias, args.segundos)
    salida = args.salida or Path("salida") / f"parrilla_{args.fecha.isoformat()}.xlsx"
    exportar(parrilla, salida, conf.equipo_plataforma)

    pendientes = sum(1 for i in parrilla.incidencias if i.gravedad == "PENDIENTE")
    sin_equipo = sum(1 for t in parrilla.tareas if t.id not in parrilla.asignadas)
    print(f"{len(vuelos)} vuelos, {len(parrilla.reparto.equipos)} equipos, "
          f"{len(parrilla.reparto.jardineras)} jardineras, {sin_equipo} tareas sin equipo, "
          f"{pendientes} incidencias pendientes.")
    print(f"Parrilla guardada en {salida}")


if __name__ == "__main__":
    main()
