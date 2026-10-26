"""Uso:
  planer-mes --mes 2026-11 --vuelos Flights-noviembre.xlsx --referencia cuadrante_octubre.xlsx --mes-referencia 2026-10

Genera el cuadrante del mes con los horarios de cada persona a partir de los vuelos del mes.
El cuadrante de referencia (el del mes anterior) dice quién hay, su función, su rotación y sus horas.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .configuracion import Configuracion
from .importar.cuadrante import leer_cuadrante
from .importar.vuelos import leer_vuelos
from .mensual import aprender_perfiles, dias_del_mes, planificar_mes
from .mensual_excel import exportar_mes


def _mes(texto: str) -> tuple[int, int]:
    anio, mes = texto.split("-")
    return int(anio), int(mes)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Genera el cuadrante mensual a partir de la programación de vuelos.")
    p.add_argument("--mes", required=True, type=_mes, help="Mes a planificar (AAAA-MM)")
    p.add_argument("--vuelos", required=True, help="Programación de vuelos del mes (Flights, PACOTRON u OMS)")
    p.add_argument("--referencia", required=True, help="Cuadrante de un mes anterior con la plantilla")
    p.add_argument("--mes-referencia", required=True, type=_mes, help="Mes del cuadrante de referencia (AAAA-MM)")
    p.add_argument("--config", default="config/base.yaml")
    p.add_argument("--salida", help="Excel de salida (por defecto salida/cuadrante_AAAA-MM.xlsx)")
    p.add_argument("--horas-locales", action="store_true", help="Las horas del archivo ya son locales, no Zulu")
    p.add_argument("--con-nombres", action="store_true", help="Mostrar nombres (por defecto solo códigos)")
    p.add_argument("--segundos-dia", type=float, default=20, help="Tiempo máximo del optimizador por día")
    args = p.parse_args(argv)

    conf = Configuracion.cargar(args.config)
    dias_ref = dias_del_mes(*args.mes_referencia)
    perfiles = aprender_perfiles(leer_cuadrante(args.referencia, args.mes_referencia[0]), dias_ref, conf)
    vuelos = {d: leer_vuelos(args.vuelos, d, conf.zona_horaria, horas_utc=not args.horas_locales)[0]
              for d in dias_del_mes(*args.mes)}
    cm = planificar_mes(vuelos, perfiles, dias_ref[0], conf, args.segundos_dia)
    salida = args.salida or Path("salida") / f"cuadrante_{args.mes[0]}-{args.mes[1]:02d}.xlsx"
    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    exportar_mes(cm, salida, args.con_nombres)
    sin_cubrir = sum(dp.deficit(r) for dp in cm.dias for r in ("TL", "PB/TOW", "Operario")) / 60
    print(f"{len(perfiles)} personas, {sum(len(v) for v in vuelos.values())} vuelos, "
          f"{sin_cubrir:.0f} horas-persona sin cubrir. Cuadrante guardado en {salida}")


if __name__ == "__main__":
    main()
