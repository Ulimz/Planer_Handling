"""Fichas del personal de una base (código, función, contrato, rotación, capacitaciones) y el filtro.

Las fichas salen de lo que la base ya ha subido en «Datos»: el último cuadrante real, los contratos
y la formación. No hace falta ningún nombre: con esto el programa organiza los turnos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..anual import Rotacion, aprender_rotacion
from ..archivo import Archivo
from ..configuracion import Configuracion
from ..desde_cuadrante import empleados_desde_cuadrante
from ..importar.vuelos import clave
from ..importar.habilitaciones import clave_persona
from ..mensual import dias_del_mes


def fichas_de_la_base(arch: Archivo, conf: Configuracion) -> list[dict]:
    meses = [(a, m) for a, m, hay in arch.meses() if "real" in hay]
    if not meses:
        return []
    anio, mes = meses[0]
    filas = arch.cuadrante(anio, mes, "real")
    contratos = {clave(k): v for k, v in (arch.contratos() or {}).items()}
    formacion = arch.formacion()
    empleados, _ = empleados_desde_cuadrante(filas, conf, formacion)
    dias = dias_del_mes(anio, mes)
    fichas = []
    for fila, emp in zip(filas, empleados):
        rot = aprender_rotacion(fila, dias)
        ficha_f = (formacion or {}).get(clave_persona(fila.nombre))
        fichas.append({
            "codigo": fila.nombre, "funcion": fila.funcion, "categoria": emp.categoria,
            "contrato": contratos.get(clave(fila.nombre)) or (ficha_f.contrato if ficha_f else ""),
            "rotacion": rot.patron, "ancla": rot.ancla.isoformat() if rot.ancla else "",
            "fases": {str(k): v for k, v in rot.fases.items()},
            "capacitaciones": sorted({h.nombre for h in emp.habilitaciones}),
        })
    return fichas


@dataclass
class Filtro:
    bases: list[str] | None = None            # códigos de base (ALC…)
    funciones: list[str] | None = None
    capacitaciones: list[str] | None = None   # tiene TODAS estas
    contratos: list[str] | None = None
    rotaciones: list[str] | None = None
    texto: str = ""                           # parte del código


def filtrar(personas: list, filtro: Filtro, base_de) -> list:
    """`personas`: fichas (modelo.Persona); `base_de(persona)` -> código de su base."""
    resultado = []
    texto = filtro.texto.strip().upper()
    for p in personas:
        if filtro.bases and base_de(p) not in filtro.bases:
            continue
        if filtro.funciones and p.funcion not in filtro.funciones:
            continue
        if filtro.contratos and p.contrato not in filtro.contratos:
            continue
        if filtro.rotaciones and p.rotacion not in filtro.rotaciones:
            continue
        if filtro.capacitaciones and not set(filtro.capacitaciones) <= set(p.capacitaciones or []):
            continue
        if texto and texto not in p.codigo.upper():
            continue
        resultado.append(p)
    return resultado


def estado_del_dia(persona, dia: date, arch: Archivo | None = None, colores: dict[str, str] | None = None) -> str:
    """«Trabaja 06:00-14:00», «Libra», el motivo de la ausencia o «Sin datos». Primero el cuadrante
    guardado de ese mes (el del programa si lo hay, si no el real); si no hay, lo que dice su rotación."""
    from ..archivo import texto_celda
    if arch is not None:
        for tipo in ("programa", "real"):
            filas = arch.cuadrante(dia.year, dia.month, tipo)
            fila = next((f for f in filas or [] if f.nombre == persona.codigo), None)
            if fila is None:
                continue
            jornada, marca = fila.jornadas.get(dia), fila.marcas_vacias.get(dia, "")
            motivo = next((m for m, c in (colores or {}).items() if c == ((jornada.marca if jornada else "") or marca)), "")
            if motivo:
                return motivo
            return f"Trabaja {texto_celda(jornada)}" if jornada and jornada.tramos else "Libra"
    if persona.rotacion and persona.ancla:
        rot = Rotacion(persona.funcion, persona.codigo, persona.rotacion, 1.0, date.fromisoformat(persona.ancla),
                       {int(k): v for k, v in (persona.fases or {}).items()})
        marca = rot.dia(dia)
        if marca in ("M", "T"):
            return f"Trabaja ({'mañana' if marca == 'M' else 'tarde'}, según su rotación)"
        if marca == "":
            return "Libra (según su rotación)"
    return "Sin datos"
