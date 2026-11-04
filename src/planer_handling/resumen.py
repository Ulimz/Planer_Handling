"""Resumen de un cuadrante frente a los vuelos: cuánta gente hay en cada franja de 15 minutos y
cuánta piden los vuelos. Sirve para cualquier cuadrante, el del programa o uno hecho a mano."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .configuracion import Configuracion
from .importar.cuadrante import FilaCuadrante
from .mensual import (PASO, DiaPlanificado, Jornada, aprender_perfiles, cobertura, demanda_del_dia,
                      emparejar_giros, sustituciones)
from .modelos import Vuelo


@dataclass
class ResumenDia:
    dia: date
    vuelos: int
    personas: int
    horas: float
    sin_cubrir: float               # horas-persona que piden los vuelos y nadie cubre
    tl_pb_como_operario: float      # horas que tapa alguien de otra categoría que sobra (en Azul, TL o PB de operario)
    plan: DiaPlanificado


def resumir(filas: list[FilaCuadrante], vuelos_por_dia: dict[date, list[Vuelo]], conf: Configuracion,
            dias_referencia: list[date]) -> list[ResumenDia]:
    """`dias_referencia`: los días del cuadrante, para saber la función de cada persona."""
    perfiles = aprender_perfiles(filas, dias_referencia, conf)
    fila_de = {f.nombre: f for f in filas}
    marcas = conf.datos.get("marcas", {})
    resultado = []
    for dia in sorted(vuelos_por_dia):
        vuelos = emparejar_giros(vuelos_por_dia[dia])
        jornadas = []
        for p in perfiles:
            j = fila_de[p.empleado.nombre].jornadas.get(dia)
            marca = marcas.get(j.marca) if j else None
            if j and j.tramos and not (marca and not marca["disponible"]):
                jornadas.append(Jornada(p, dia, j.tramos))
        demanda = demanda_del_dia(vuelos, conf)
        cub = cobertura(jornadas, demanda)
        ayuda = {r: [x for x in f if x in demanda] for r, f in sustituciones(conf).items() if r in demanda}
        sin_cubrir = sustituye = 0
        for k in range(len(next(iter(demanda.values())))):
            sobra = {r: max(0, cub[r][k] - demanda[r][k]) for r in demanda}
            for r in demanda:
                falta = max(0, demanda[r][k] - cub[r][k])
                for x in ayuda.get(r, []):
                    tapa = min(falta, sobra[x])
                    sobra[x] -= tapa
                    falta -= tapa
                    sustituye += tapa
                sin_cubrir += falta
        horas = sum(j.minutos for j in jornadas if j.perfil.empleado.categoria in demanda) / 60
        resultado.append(ResumenDia(dia, len(vuelos), len(jornadas), round(horas, 1), sin_cubrir * PASO / 60,
                                    sustituye * PASO / 60, DiaPlanificado(dia, len(vuelos), demanda, cub, jornadas)))
    return resultado
