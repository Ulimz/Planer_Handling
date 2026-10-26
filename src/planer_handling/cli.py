"""Uso:
  planer --fecha 2027-07-15 --vuelos vuelos.xlsx --plantilla plantilla.xlsx
  planer --fecha 2025-02-06 --vuelos parrillas.xlsx --hoja 06-02 --cuadrante turnos.xlsx
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .configuracion import Configuracion
from .desde_cuadrante import generar_parrilla_cuadrante
from .importar.cuadrante import leer_cuadrante
from .importar.parrilla_real import leer_vuelos_parrilla
from .importar.plantilla import leer_plantilla
from .importar.vuelos import leer_vuelos
from .parrilla_excel import exportar
from .planificador import generar_parrilla


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Genera la parrilla diaria de una base de handling.")
    p.add_argument("--fecha", required=True, type=date.fromisoformat, help="Día a planificar (AAAA-MM-DD)")
    p.add_argument("--vuelos", required=True, help="Programación PACOTRON u OMS (.xlsx o .csv) o libro de parrillas")
    p.add_argument("--hoja", help="Hoja del libro de parrillas diarias de donde leer los vuelos (por ejemplo 15-10)")
    personal = p.add_mutually_exclusive_group(required=True)
    personal.add_argument("--plantilla", help="Excel con hojas Plantilla y Habilitaciones (turnos por rotación)")
    personal.add_argument("--cuadrante", help="Cuadrante mensual con el horario real de cada persona")
    p.add_argument("--config", default="config/base.yaml")
    p.add_argument("--salida", help="Excel de salida (por defecto salida/parrilla_AAAA-MM-DD.xlsx)")
    p.add_argument("--horas-locales", action="store_true", help="Las horas del archivo ya son locales, no Zulu")
    p.add_argument("--con-nombres", action="store_true", help="Mostrar nombres en la parrilla (por defecto solo códigos)")
    p.add_argument("--segundos", type=float, default=30, help="Tiempo máximo del optimizador por asignación")
    args = p.parse_args(argv)

    conf = Configuracion.cargar(args.config)
    if args.hoja:
        vuelos, _ = leer_vuelos_parrilla(args.vuelos, args.hoja, args.fecha)
        incidencias = []
    else:
        vuelos, incidencias = leer_vuelos(args.vuelos, args.fecha, conf.zona_horaria, horas_utc=not args.horas_locales)
    if args.cuadrante:
        filas = leer_cuadrante(args.cuadrante, args.fecha.year)
        parrilla = generar_parrilla_cuadrante(args.fecha, vuelos, filas, conf, incidencias, args.segundos)
    else:
        parrilla = generar_parrilla(args.fecha, vuelos, leer_plantilla(args.plantilla), conf, incidencias, args.segundos)
    salida = args.salida or Path("salida") / f"parrilla_{args.fecha.isoformat()}.xlsx"
    exportar(parrilla, salida, conf.equipo_plataforma, args.con_nombres)

    pendientes = sum(1 for i in parrilla.incidencias if i.gravedad == "PENDIENTE")
    sin_equipo = sum(1 for t in parrilla.tareas if t.id not in parrilla.asignadas)
    print(f"{len(vuelos)} vuelos, {len(parrilla.reparto.equipos)} equipos, "
          f"{len(parrilla.reparto.jardineras)} jardineras, {sin_equipo} tareas sin equipo, "
          f"{pendientes} incidencias pendientes.")
    print(f"Parrilla guardada en {salida}")


if __name__ == "__main__":
    main()
