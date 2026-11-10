"""Parrilla de pasaje del día: quién factura cada vuelo, quién lo embarca y quién está en los
puestos fijos (oficina, lost and found…), con la gente de pasaje que trabaja ese día según el
cuadrante. Las cifras salen de `pasaje` en la configuración (ver mensual.demanda_pasaje)."""
from __future__ import annotations

import math

from dataclasses import dataclass, field
from datetime import date

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from .configuracion import Configuracion
from .importar.cuadrante import FilaCuadrante
from .modelos import Vuelo, hhmm

PASO = 15                 # se reparte franja a franja de 15 minutos; así caben los relevos


@dataclass
class TareaPasaje:
    puesto: str                       # "Facturación", "Embarque", "Oficina"…
    vuelo: str
    inicio: int
    fin: int
    plazas: int
    agentes: dict[str, list[list[int]]] = field(default_factory=dict)   # agente -> tramos [desde, hasta]
    sin_cubrir: int = 0                                                 # minutos-persona sin nadie
    categoria: str = "Pasaje"                                          # quién la hace (categoría del cuadrante)


RESPONSABLE = "Responsable pasaje"


def _minutos(valor) -> int:
    """"08:00" -> 480; un número se toma como minutos."""
    if isinstance(valor, str):
        h, m = valor.split(":")
        return int(h) * 60 + int(m)
    return int(valor)


def _fijo(valor) -> tuple[int, str]:
    """Un puesto fijo: `2` (personas de la categoría Pasaje) o `{personas: 2, categoria: Operaciones}`."""
    if isinstance(valor, dict):
        return int(valor.get("personas", 0)), valor.get("categoria", "Pasaje")
    return int(valor), "Pasaje"


def categorias(conf: Configuracion) -> list[str]:
    """Categorías de pasaje que se planifican: Pasaje, Responsable pasaje y las de los puestos fijos."""
    fijas = [_fijo(v)[1] for v in conf.datos.get("pasaje", {}).get("puestos_fijos", {}).values()]
    return list(dict.fromkeys(["Pasaje", RESPONSABLE] + fijas))


def _por_franjas(puesto: str, ventanas: list[tuple[int, int]], plazas) -> list[tuple]:
    """Bloques de PASO minutos con las plazas que da `plazas(n)` según cuántas ventanas tocan la franja
    (n > 0); las franjas seguidas con las mismas plazas se juntan en un bloque."""
    if not ventanas:
        return []
    desde = min(i for i, _ in ventanas) // PASO * PASO
    hasta = max(f for _, f in ventanas)
    bloques: list[list] = []
    for m in range(desde, hasta, PASO):
        n = sum(1 for i, f in ventanas if i < m + PASO and f > m)
        p = plazas(n) if n else 0
        if bloques and bloques[-1][3] == m and bloques[-1][4] == p:
            bloques[-1][3] = m + PASO
        else:
            bloques.append([puesto, "", m, m + PASO, p, "Pasaje"])
    return [tuple(b) for b in bloques if b[4] > 0]


def bloques(vuelos: list[Vuelo], regla: dict) -> tuple[list[tuple], tuple[int, int] | None]:
    """Lo que pide el pasaje del día: (puesto, vuelo, inicio, fin, personas, categoría) y el tramo de la
    operación (desde un poco antes de la primera facturación hasta la última salida o un rato después
    de la última llegada), en el que están los puestos fijos y los responsables.

    - facturacion: `personas` por vuelo entre `abre_antes_std` y `cierra_antes_std`. Con `compartida`
      (mostradores para todos los vuelos), en cada franja hay `base` personas más una por cada
      `vuelos_por_persona` vuelos con el check-in abierto.
    - embarque: `personas` por puerta desde `desde_antes_std` (o el de `primera_ola` para las salidas
      hasta su hora `hasta`) hasta `hasta_antes_std`. `reserva`: personas de más mientras hay
      facturación o embarque (van de puerta en puerta, cubren incidencias…).
    """
    if not regla.get("activo") or not vuelos:
        return [], None
    fac, emb = regla.get("facturacion", {}), regla.get("embarque", {})
    compartida, ola = fac.get("compartida"), emb.get("primera_ola")
    resultado, momentos, facturando, abiertos = [], [], [], []
    for v in vuelos:
        if v.std is not None:
            codigo = v.vuelo_out or v.codigo
            abre, cierra = v.std - fac.get("abre_antes_std", 150), v.std - fac.get("cierra_antes_std", 40)
            antes = emb.get("desde_antes_std", 45)
            if ola and v.std <= _minutos(ola.get("hasta", 0)):
                antes = ola.get("desde_antes_std", antes)
            puerta, sale = v.std - antes, v.std - emb.get("hasta_antes_std", 0)
            if not compartida:
                resultado.append(("Facturación", codigo, abre, cierra, fac.get("personas", 0), "Pasaje"))
            resultado.append(("Embarque", codigo, puerta, sale, emb.get("personas", 0), "Pasaje"))
            facturando.append((abre, cierra))
            abiertos += [(abre, cierra), (puerta, sale)]
            momentos += [abre, v.std]
        if v.sta is not None:
            momentos.append(v.sta + regla.get("despues_ultima_llegada", 60))
    if compartida:
        base, por = compartida.get("base", 0), compartida.get("vuelos_por_persona", 1)
        resultado += _por_franjas("Facturación", facturando, lambda n: base + math.ceil(n / por))
    if emb.get("reserva"):
        resultado += _por_franjas("Apoyo embarque", abiertos, lambda n: emb["reserva"])
    if not momentos:
        return resultado, None
    inicio, fin = min(momentos) - regla.get("antes_primera_facturacion", 15), max(momentos)
    for puesto, valor in regla.get("puestos_fijos", {}).items():
        personas, categoria = _fijo(valor)
        resultado.append((puesto, "", inicio, fin, personas, categoria))
    return resultado, (inicio, fin)


def tareas_pasaje(vuelos: list[Vuelo], conf: Configuracion) -> list[TareaPasaje]:
    lista, _ = bloques(vuelos, conf.datos.get("pasaje", {}))
    tareas = [TareaPasaje(p, v, i, f, n, categoria=c) for p, v, i, f, n, c in lista]
    return sorted(tareas, key=lambda t: (t.inicio, t.puesto))


def agentes_del_dia(filas: list[FilaCuadrante], dia: date, conf: Configuracion, categoria: str,
                    ausentes: set[str] = frozenset()) -> dict[str, list[tuple[int, int]]]:
    """Nombre -> tramos de quien es de esa categoría y trabaja ese día (sin los ausentes)."""
    funciones = conf.datos.get("funciones", {})
    marcas = conf.datos.get("marcas", {})
    resultado = {}
    for f in filas:
        j = f.jornadas.get(dia)
        marca = marcas.get(j.marca) if j else None
        if (funciones.get(f.funcion, {}).get("categoria") == categoria and j and j.tramos
                and not (marca and not marca["disponible"]) and f.nombre not in ausentes):
            resultado[f.nombre] = j.tramos
    return resultado


def asignar(tareas: list[TareaPasaje], agentes: dict[str, list[tuple[int, int]]]) -> None:
    """Reparto franja a franja: quien ya está en una tarea sigue en ella mientras esté de turno; las
    plazas libres se dan a quien está de turno y libre, primero a quien seguirá de turno más tiempo
    (menos relevos) y con menos minutos asignados."""
    if not tareas:
        return
    carga = {a: 0 for a in agentes}
    inicio = min(t.inicio for t in tareas) // PASO * PASO
    fin = max(t.fin for t in tareas)
    en_tarea: dict[int, set[str]] = {i: set() for i in range(len(tareas))}

    def de_turno(a: str, m: int) -> int | None:
        """Hasta cuándo sigue de turno `a` si lo está en el minuto m."""
        return next((f for i, f in agentes[a] if i <= m and m + PASO <= f), None)

    for m in range(inicio, fin, PASO):
        activas = [i for i, t in enumerate(tareas) if t.inicio <= m < t.fin]
        ocupados: set[str] = set()
        for i in activas:                                   # los que siguen
            seguir = {a for a in en_tarea[i] if de_turno(a, m) is not None}
            en_tarea[i] = set(sorted(seguir)[:tareas[i].plazas])
            ocupados |= en_tarea[i]
        for i in sorted(activas, key=lambda i: tareas[i].fin):
            t = tareas[i]
            libres = [a for a in agentes if a not in ocupados and de_turno(a, m) is not None]
            libres.sort(key=lambda a: (-min(de_turno(a, m), t.fin), carga[a]))
            nuevos = libres[:t.plazas - len(en_tarea[i])]
            en_tarea[i] |= set(nuevos)
            ocupados |= set(nuevos)
            t.sin_cubrir += PASO * (t.plazas - len(en_tarea[i]))
            for a in en_tarea[i]:
                carga[a] += PASO
                tramos = t.agentes.setdefault(a, [])
                if tramos and tramos[-1][1] == m:
                    tramos[-1][1] = m + PASO
                else:
                    tramos.append([m, m + PASO])
        for i in en_tarea:
            if i not in activas:
                en_tarea[i] = set()


def anadir_hoja(ruta, tareas: list[TareaPasaje], responsables: dict[str, list[tuple[int, int]]]) -> None:
    """Añade la hoja "Pasaje" al Excel de la parrilla del día."""
    wb = load_workbook(ruta)
    ws = wb.create_sheet("Pasaje")
    negrita, cabecera = Font(bold=True), PatternFill("solid", fgColor="FFD9E1F2")
    falta = PatternFill("solid", fgColor="FFF8CBAD")
    ws.append(["Responsables de pasaje"] + [f"{n} ({' + '.join(f'{hhmm(i)}-{hhmm(f)}' for i, f in t)})"
                                            for n, t in sorted(responsables.items(), key=lambda x: x[1][0])])
    ws.append([])
    ws.append(["Desde", "Hasta", "Puesto", "Vuelo", "Personas", "Asignados", "Minutos sin cubrir"])
    for celda in ws[ws.max_row]:
        celda.font, celda.fill = negrita, cabecera
    ws["A1"].font = negrita
    for t in tareas:
        # Quien hace la tarea entera, solo el código; quien hace un relevo, con sus horas.
        asignados = ", ".join(
            a if len(x) == 1 and x[0][0] < t.inicio + PASO and x[0][1] >= t.fin else f"{a} ({' + '.join(f'{hhmm(i)}-{hhmm(f)}' for i, f in x)})"
            for a, x in sorted(t.agentes.items(), key=lambda kv: kv[1][0][0]))
        ws.append([hhmm(t.inicio), hhmm(t.fin), t.puesto, t.vuelo, t.plazas, asignados, t.sin_cubrir or None])
        if t.sin_cubrir:
            ws.cell(ws.max_row, 7).fill = falta
    for col, ancho in zip("ABCDEFG", (8, 8, 16, 10, 10, 90, 12)):
        ws.column_dimensions[col].width = ancho
    wb.save(ruta)
