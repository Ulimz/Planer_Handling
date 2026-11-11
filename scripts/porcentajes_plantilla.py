"""Porcentajes de una plantilla real, sin nombres: cuántas personas hay de cada función y qué parte
tiene cada contrato, rotación, capacitación y turno. Sirven para crear una plantilla ficticia que se
parece a la real (ver plantilla_ficticia.py) sin copiar a nadie.

Uso:
  python scripts/porcentajes_plantilla.py --cuadrante CUADRANTE.xlsx --anio 2026 --mes 11 \
      [--contratos CONTRATOS.xlsx] [--formacion FORMACION.xlsx] [--config config/base.yaml] \
      --salida porcentajes.yaml

La salida solo tiene totales y proporciones: ningún nombre ni código de persona. Aun así describe la
plantilla de una empresa real: guárdala fuera del repositorio.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from planer_handling.anual import aprender_rotacion                       # noqa: E402
from planer_handling.configuracion import Configuracion                    # noqa: E402
from planer_handling.desde_cuadrante import empleados_desde_cuadrante      # noqa: E402
from planer_handling.importar.contratos import leer_contratos              # noqa: E402
from planer_handling.importar.cuadrante import leer_cuadrante              # noqa: E402
from planer_handling.importar.habilitaciones import clave_persona, leer_habilitaciones   # noqa: E402
from planer_handling.mensual import MEDIODIA, dias_del_mes                 # noqa: E402
from planer_handling.modelos import hhmm                                    # noqa: E402


def texto_turno(tramos) -> str:
    """"06:00-14:00" o el partido "06:00-10:00 / 15:00-19:00"."""
    return " / ".join(f"{hhmm(a)}-{hhmm(b)}" for a, b in tramos)


def proporciones(contador: Counter, minimo: float = 0.0) -> dict:
    total = sum(contador.values())
    if not total:
        return {}
    return {str(k): round(v / total, 4) for k, v in contador.most_common() if v / total >= minimo}


def calcular(cuadrante: Path, anio: int, mes: int, conf: Configuracion, contratos: Path | None,
             formacion: Path | None) -> dict:
    filas = leer_cuadrante(cuadrante, anio)
    dias = dias_del_mes(anio, mes)
    fichas = leer_habilitaciones(formacion, conf) if formacion else None
    empleados, _ = empleados_desde_cuadrante(filas, conf, fichas)
    contrato_de = {clave_persona(k): v for k, v in (leer_contratos(contratos) if contratos else {}).items()}

    personas = Counter()
    contrato, rotacion, posicion, fases, capacit = (defaultdict(Counter) for _ in range(5))
    turnos = defaultdict(lambda: {"M": Counter(), "T": Counter()})
    dias_irregular = defaultdict(list)
    horas = defaultdict(lambda: defaultdict(list))      # función -> contrato -> horas del mes de cada uno
    for fila, emp in zip(filas, empleados):
        f = fila.funcion
        personas[f] += 1
        if (c := contrato_de.get(clave_persona(fila.nombre))) and not c.startswith("¿"):
            contrato[f][c] += 1
        for h in emp.habilitaciones:
            capacit[f][h.nombre] += 1
        minutos = sum(b - a for d in dias if (j := fila.jornadas.get(d)) and j.tramos for a, b in j.tramos)
        if minutos:
            horas[f][contrato_de.get(clave_persona(fila.nombre)) or "?"].append(minutos / 60)
        rot = aprender_rotacion(fila, dias)
        rotacion[f][rot.patron] += 1
        if rot.ciclo():
            largo = sum(rot.ciclo())
            posicion[f][f"{rot.patron}:{(dias[0] - rot.ancla).days % largo}"] += 1
            fases[f][f"{rot.patron}:" + "".join(rot.fases.get(p, "-") for p in range(rot.ciclo()[0]))] += 1
        else:
            dias_irregular[f].append(sum(1 for d in dias if (j := fila.jornadas.get(d)) and j.tramos))
        for d in dias:
            j = fila.jornadas.get(d)
            if j and j.tramos:
                turnos[f]["M" if j.tramos[0][0] < MEDIODIA else "T"][texto_turno(j.tramos)] += 1

    resultado = {"mes_referencia": f"{anio}-{mes:02d}", "dias_del_mes": len(dias), "total": sum(personas.values()),
                 "horas_total": round(sum(sum(v) for c in horas.values() for v in c.values())), "funciones": {}}
    for f, n in personas.most_common():
        resultado["funciones"][f] = {
            "personas": n,
            "contratos": proporciones(contrato[f]),
            "con_contrato_conocido": sum(contrato[f].values()),
            "rotaciones": proporciones(rotacion[f]),
            "posiciones": proporciones(posicion[f]),
            "fases": proporciones(fases[f]),
            "capacitaciones": {h: round(v / n, 4) for h, v in capacit[f].most_common()},
            "turnos_manana": proporciones(turnos[f]["M"], 0.005),
            "turnos_tarde": proporciones(turnos[f]["T"], 0.005),
            "horas_mes": {c: round(sum(v) / len(v), 1) for c, v in horas[f].items()},
            "dias_trabajo_irregular": round(sum(dias_irregular[f]) / len(dias_irregular[f]), 1)
            if dias_irregular[f] else 0,
        }
    return resultado


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cuadrante", required=True, type=Path)
    p.add_argument("--anio", required=True, type=int)
    p.add_argument("--mes", required=True, type=int)
    p.add_argument("--contratos", type=Path)
    p.add_argument("--formacion", type=Path)
    p.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config" / "base.yaml")
    p.add_argument("--salida", required=True, type=Path)
    a = p.parse_args(argv)
    datos = calcular(a.cuadrante, a.anio, a.mes, Configuracion.cargar(a.config), a.contratos, a.formacion)
    datos = {"aviso": "Solo totales y proporciones, sin nombres ni códigos. No subir al repositorio.",
             "creado": date.today().isoformat(), **datos}
    a.salida.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{datos['total']} personas en {len(datos['funciones'])} funciones -> {a.salida}")
    for f, x in datos["funciones"].items():
        print(f"  {f:8} {x['personas']:4}  contratos {x['contratos']}  rotaciones {x['rotaciones']}")


if __name__ == "__main__":
    main()
