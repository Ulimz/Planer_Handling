"""Plantilla ficticia de una base a partir de los porcentajes de una real (porcentajes_plantilla.py).

Nadie es real: cada persona es un código (P0001…) y lo único que se copia de la plantilla real son
las proporciones: cuántos de cada función, qué parte tiene cada contrato, rotación y capacitación, y
qué turnos se hacen. Sale lo que hace falta para probar AEROS en una base piloto:

  cuadrante_ficticio_AAAA-MM.xlsx   cuadrante de cada mes (formato que lee AEROS); la rotación sigue
                                    de un mes al siguiente
  contratos_ficticios.xlsx          Empleado, Contrato
  formacion_ficticia.xlsx           Empleado, Contrato y una columna por formación
  plantilla_ficticia.xlsx           ficha de cada código y la comprobación de porcentajes

Uso:
  python scripts/plantilla_ficticia.py --porcentajes porcentajes.yaml --desde 2026-10 --hasta 2026-11 \
      [--personas 385] [--semilla 7] [--config config/base.yaml] --salida carpeta/
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from planer_handling.archivo import exportar_cuadrante                     # noqa: E402
from planer_handling.configuracion import Configuracion                    # noqa: E402
from planer_handling.importar.cuadrante import FilaCuadrante, Jornada, tramos   # noqa: E402
from planer_handling.mensual import ROTACIONES, dias_del_mes               # noqa: E402

TC = {"TC", "TCC"}            # contratos de jornada completa: turnos de 7,5 h o más
JORNADA_COMPLETA = 7 * 60 + 30


def reparto(n: int, proporciones: dict) -> list:
    """`n` elementos repartidos según `proporciones` (resto mayor): la lista de etiquetas, n en total."""
    if n <= 0 or not proporciones:
        return []
    total = sum(proporciones.values())
    exactas = {k: n * v / total for k, v in proporciones.items()}
    cuantos = {k: int(x) for k, x in exactas.items()}
    for k in sorted(exactas, key=lambda k: exactas[k] - cuantos[k], reverse=True)[:n - sum(cuantos.values())]:
        cuantos[k] += 1
    return [k for k, c in cuantos.items() for _ in range(c)]


def _dura(turno: str) -> int:
    return sum(b - a for a, b in tramos(turno.replace(" / ", " ").replace("-", " ")))


def _turnos(opciones: dict, completa: bool, objetivo: float | None = None) -> dict:
    """Turnos que encajan con el contrato: de 7,5 h o más para jornada completa, menos para el resto. Con
    `objetivo` (minutos por día), los que se acercan a él en una hora o menos."""
    elegidos = {t: p for t, p in opciones.items() if (_dura(t) >= JORNADA_COMPLETA) == completa} or opciones
    if objetivo and elegidos:
        cerca = {t: p for t, p in elegidos.items() if abs(_dura(t) - objetivo) <= 60}
        if not cerca:
            mejor = min(elegidos, key=lambda t: abs(_dura(t) - objetivo))
            cerca = {mejor: 1}
        return cerca
    return elegidos


def _elegir(rng: random.Random, opciones: dict) -> str:
    return rng.choices(list(opciones), weights=list(opciones.values()))[0]


def generar(porcentajes: dict, meses: list[tuple[int, int]], personas: int | None, semilla: int):
    """Filas de cuadrante (un mes tras otro, la rotación sigue) y la ficha de cada código."""
    rng = random.Random(semilla)
    funciones = porcentajes["funciones"]
    total = personas or porcentajes["total"]
    por_funcion = Counter(reparto(total, {f: x["personas"] for f, x in funciones.items()}))
    dias = [d for a, m in meses for d in dias_del_mes(a, m)]
    ref = date.fromisoformat(porcentajes["mes_referencia"] + "-01")   # las posiciones son de este día
    contrato_comun = Counter()
    for x in funciones.values():
        contrato_comun.update({c: p * x["personas"] for c, p in x["contratos"].items()})

    fichas, filas, n = [], [], 0
    for funcion, x in funciones.items():
        cuantos = por_funcion[funcion]
        if not cuantos:
            continue
        contratos = reparto(cuantos, x["contratos"] or dict(contrato_comun))
        rotaciones = reparto(cuantos, x["rotaciones"])
        rng.shuffle(contratos)
        rng.shuffle(rotaciones)
        posiciones = {p: reparto(rotaciones.count(p), {k.split(":")[1]: v for k, v in x["posiciones"].items()
                                                         if k.startswith(p + ":")} or {"0": 1}) for p in ROTACIONES}
        fases = {p: reparto(rotaciones.count(p), {k.split(":")[1]: v for k, v in x["fases"].items()
                                                    if k.startswith(p + ":")} or {"M" * ROTACIONES[p][0]: 1})
                 for p in ROTACIONES}
        for lista in (*posiciones.values(), *fases.values()):
            rng.shuffle(lista)
        quien_tiene = {h: set(rng.sample(range(cuantos), round(p * cuantos))) for h, p in x["capacitaciones"].items()}
        for i in range(cuantos):
            n += 1
            codigo, contrato, rot = f"P{n:04d}", contratos[i], rotaciones[i]
            completa = contrato in TC
            # Turno de cada día para que el mes salga con las horas de su función y contrato en la real.
            on_off = ROTACIONES.get(rot)
            dias_mes = (porcentajes["dias_del_mes"] * on_off[0] / sum(on_off)) if on_off else \
                max(1.0, x["dias_trabajo_irregular"])
            horas_mes = (x.get("horas_mes") or {}).get(contrato) or (x.get("horas_mes") or {}).get("?")
            objetivo = horas_mes * 60 / dias_mes if horas_mes else None
            manana = _turnos(x["turnos_manana"], completa, objetivo)
            tarde = _turnos(x["turnos_tarde"], completa, objetivo)
            habitual = {"M": _elegir(rng, manana) if manana else "", "T": _elegir(rng, tarde) if tarde else ""}
            fila = FilaCuadrante(funcion, codigo, n + 1)
            ficha = {"Código": codigo, "Función": funcion, "Contrato": contrato, "Rotación": rot, "Posición": "",
                     "Fases": "", "Capacitaciones": ", ".join(h for h in quien_tiene if i in quien_tiene[h])}
            if rot in ROTACIONES:
                on, off = ROTACIONES[rot]
                pos0, patron = int(posiciones[rot].pop()), fases[rot].pop()
                ficha["Posición"], ficha["Fases"] = pos0, patron
                trabaja = {}
                for d in dias:
                    pos = (pos0 + (d - ref).days) % (on + off)
                    trabaja[d] = (pos < on, patron[pos] if pos < on else "")
            else:
                cuantos_dias = min(len(dias), round(x["dias_trabajo_irregular"] * len(dias) / porcentajes["dias_del_mes"]))
                elegidos = set(rng.sample(dias, cuantos_dias))
                trabaja = {d: (d in elegidos, rng.choice("MT")) for d in dias}
            for d, (si, fase) in trabaja.items():
                if not si:
                    continue
                turno = habitual.get(fase) or habitual["M"] or habitual["T"]
                if fase == "-" or not turno:
                    turno = habitual["M"] or habitual["T"]
                if turno:
                    fila.jornadas[d] = Jornada(tramos(turno.replace(" / ", " ").replace("-", " ")))
            filas.append(fila)
            fichas.append(ficha)
    return filas, fichas


def formacion(fichas: list[dict], conf: Configuracion) -> pd.DataFrame:
    """Una columna por formación de la configuración: 1 si tiene todo lo que da esa formación, 0 si no."""
    columnas = {c: r["habilitaciones"] for c, r in conf.datos.get("habilitaciones_por_persona", {})
                .get("columnas", {}).items() if not r.get("solo_quita")}
    filas = []
    for f in fichas:
        tiene = set(filter(None, f["Capacitaciones"].split(", ")))
        filas.append({"EMPLEADO": f["Código"], "CONTRATO": f["Contrato"],
                      **{c: 1 if set(h) <= tiene else 0 for c, h in columnas.items()}})
    return pd.DataFrame(filas)


def comprobar(objetivo: dict, obtenido: dict) -> pd.DataFrame:
    filas = []
    for f, x in objetivo["funciones"].items():
        y = obtenido["funciones"].get(f, {})
        for campo in ("contratos", "rotaciones", "capacitaciones"):
            for k, v in x[campo].items():
                filas.append({"Función": f, "Qué": campo, "Valor": k, "Real %": round(100 * v, 1),
                              "Ficticia %": round(100 * y.get(campo, {}).get(k, 0), 1)})
        filas.append({"Función": f, "Qué": "personas", "Valor": "",
                      "Real %": round(100 * x["personas"] / objetivo["total"], 1),
                      "Ficticia %": round(100 * y.get("personas", 0) / max(1, obtenido["total"]), 1)})
    return pd.DataFrame(filas)


def _meses(desde: str, hasta: str) -> list[tuple[int, int]]:
    a, m = map(int, desde.split("-"))
    fin = tuple(map(int, hasta.split("-")))
    meses = []
    while (a, m) <= fin:
        meses.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    if not meses:
        raise SystemExit("--hasta es anterior a --desde.")
    return meses


def main(argv: list[str] | None = None) -> None:
    import porcentajes_plantilla

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--porcentajes", required=True, type=Path)
    p.add_argument("--desde", required=True, help="primer mes, AAAA-MM")
    p.add_argument("--hasta", help="último mes, AAAA-MM (por defecto el mismo)")
    p.add_argument("--personas", type=int)
    p.add_argument("--semilla", type=int, default=7)
    p.add_argument("--config", type=Path, default=Path(__file__).resolve().parent.parent / "config" / "base.yaml")
    p.add_argument("--salida", required=True, type=Path)
    a = p.parse_args(argv)
    conf = Configuracion.cargar(a.config)
    objetivo = yaml.safe_load(a.porcentajes.read_text(encoding="utf-8"))
    meses = _meses(a.desde, a.hasta or a.desde)
    filas, fichas = generar(objetivo, meses, a.personas, a.semilla)
    a.salida.mkdir(parents=True, exist_ok=True)
    for anio, mes in meses:
        del_mes = []
        for f in filas:
            g = FilaCuadrante(f.funcion, f.nombre, f.fila)
            g.jornadas = {d: j for d, j in f.jornadas.items() if (d.year, d.month) == (anio, mes)}
            del_mes.append(g)
        cuadrante = exportar_cuadrante(del_mes, anio, mes, a.salida / f"cuadrante_ficticio_{anio}-{mes:02d}.xlsx", {})
    anio, mes = meses[-1]
    pd.DataFrame([{"Empleado": f["Código"], "Contrato": f["Contrato"]} for f in fichas]).to_excel(
        a.salida / "contratos_ficticios.xlsx", index=False)
    formacion(fichas, conf).to_excel(a.salida / "formacion_ficticia.xlsx", index=False)
    # Se vuelve a leer lo generado con los mismos lectores de AEROS y se comparan los porcentajes.
    obtenido = porcentajes_plantilla.calcular(cuadrante, anio, mes, conf, a.salida / "contratos_ficticios.xlsx",
                                              a.salida / "formacion_ficticia.xlsx")
    tabla = comprobar(objetivo, obtenido)
    with pd.ExcelWriter(a.salida / "plantilla_ficticia.xlsx") as w:
        pd.DataFrame(fichas).to_excel(w, sheet_name="Plantilla", index=False)
        tabla.to_excel(w, sheet_name="Comprobación", index=False)
    diferencia = (tabla["Real %"] - tabla["Ficticia %"]).abs()
    print(f"{len(fichas)} personas ficticias -> {a.salida}")
    if objetivo.get("horas_total"):
        miles = lambda x: f"{x:,}".replace(",", ".")  # noqa: E731
        print(f"Horas del mes: real {miles(objetivo['horas_total'])}, ficticia {miles(obtenido['horas_total'])}")
    print(f"Diferencia con la real: media {diferencia.mean():.1f} puntos, máxima {diferencia.max():.1f} "
          f"({tabla.loc[diferencia.idxmax(), 'Función']} {tabla.loc[diferencia.idxmax(), 'Qué']} "
          f"{tabla.loc[diferencia.idxmax(), 'Valor']})")


if __name__ == "__main__":
    main()
