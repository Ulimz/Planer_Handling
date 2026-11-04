"""Cómo trabaja cada empresa en plataforma: qué recursos tiene y qué tareas le pide cada vuelo.

Un recurso es lo que atiende los vuelos: un equipo completo, un grupo con su capataz, un PB suelto
que solo saca salidas, un conductor de jardinera, un coordinador de vuelos… Cada empresa los
describe en la sección `operativa` de su perfil:

    operativa:
      recursos:
        Grupo:
          puestos: [Capataz, TRT, Operario, Operario, Operario]
          turnos: [M, T, N]
          transito: 10
          tareas:
            giro: {antes_sta: 10, despues_std: 5}
        Pushback:
          puestos: [PB/TOW]
          turnos: [M, T, N]
          tareas:
            salida: {antes_std: 10, despues_std: 5}
      puede_hacer_de:
        PB/TOW: [Capataz]

Un perfil sin `operativa` (el de Azul con Ryanair) se lee de las claves de siempre
(`equipo_plataforma`, `servicio`, `jardineras`, `turnos_plataforma`…) y da lo mismo que antes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .modelos import Tarea, Vuelo

# Categorías que el perfil de Azul planifica aparte (hipódromo y mandos) o como conductor de jardinera.
CATEGORIAS_APARTE_AZUL = ["Jardinero", "Hipodromo", "Mando intermedio"]


@dataclass
class Recurso:
    """Un tipo de recurso de plataforma y las tareas que le pide cada vuelo."""
    nombre: str
    puestos: list[str]
    turnos: list[str]
    tareas: dict[str, dict]
    transito: int = 10
    # Para el cuadrante del mes: categoría de la plantilla que cubre cada puesto (si no se dice,
    # la del mismo nombre). En Azul, carretero y cintero los cubre un operario.
    cuenta_como: dict[str, str] = field(default_factory=dict)
    # Quién puede entrar en este recurso. Vacío: quien tenga la habilitación del puesto (salvo las
    # categorías que otros recursos tienen reservadas). Con categorías: solo esas.
    categorias: list[str] = field(default_factory=list)
    excluir_categorias: list[str] = field(default_factory=list)
    solo_remoto: bool = False          # solo vuelos en puesto remoto (autobuses)
    simultaneos: int = 1               # vuelos a la vez que lleva un mismo recurso (coordinador)
    max_vuelos_dia: int | None = None  # vuelos que puede llevar en un día, si hay límite
    codigo: str = ""                   # letra en el código del recurso: M01, MJ01, MP01…
    seccion: str = ""                  # cómo se llama en la parrilla
    hoja: str = ""                     # nombre de su hoja en el Excel de la parrilla
    prefijo_tarea: str = ""            # P001, J001… (identificador de cada tarea)
    tipos: dict[str, str] = field(default_factory=dict)   # nombre que se da a cada tipo de tarea
    principal: bool = False            # el recurso que hace el vuelo (equipos de la parrilla)
    nombre_puesto: dict[str, str] = field(default_factory=dict)   # cómo se llama cada puesto en la parrilla
    en_cuadrante: bool = True          # el cuadrante del mes calcula su demanda (si no, horario habitual)
    puestos_clave: list[str] = field(default_factory=list)   # sin ellos el recurso no puede salir

    @property
    def por_orden_de_codigo(self) -> bool:
        """Recurso de una sola persona elegida por categoría (la jardinera de Azul): se cubre por orden
        de código, turno a turno, sin mirar habilitaciones."""
        return len(self.puestos) == 1 and bool(self.categorias)

    def categoria_de(self, puesto: str) -> str:
        return self.cuenta_como.get(puesto, puesto)

    def personas_por_categoria(self) -> dict[str, int]:
        resultado: dict[str, int] = {}
        for puesto in self.puestos:
            c = self.categoria_de(puesto)
            resultado[c] = resultado.get(c, 0) + 1
        return resultado

    def etiquetas(self) -> list[str]:
        """Nombre de cada puesto en el equipo; los repetidos se numeran (Operario 1, Operario 2…)."""
        vistos: dict[str, int] = {}
        total = {p: self.puestos.count(p) for p in self.puestos}
        resultado = []
        for p in self.puestos:
            nombre = self.nombre_puesto.get(p, p)
            if total[p] > 1:
                vistos[p] = vistos.get(p, 0) + 1
                nombre = f"{nombre} {vistos[p]}"
            resultado.append(nombre)
        return resultado


@dataclass
class Operativa:
    recursos: list[Recurso]
    puede_hacer_de: dict[str, list[str]] = field(default_factory=dict)   # categoría -> quién la cubre si sobra
    coste_falta: dict[str, int] = field(default_factory=dict)            # cuánto pesa una franja sin cubrir

    @property
    def principal(self) -> Recurso:
        return next((r for r in self.recursos if r.principal), self.recursos[0])

    def categorias(self) -> list[str]:
        """Categorías de la plantilla que el cuadrante del mes planifica según los vuelos."""
        resultado = []
        for r in self.recursos:
            if not r.en_cuadrante:
                continue
            for c in r.personas_por_categoria():
                if c not in resultado:
                    resultado.append(c)
        return resultado


def _recurso(nombre: str, d: dict, n: int) -> Recurso:
    return Recurso(
        nombre=nombre,
        puestos=list(d["puestos"]),
        turnos=list(d["turnos"]),
        tareas=dict(d.get("tareas") or {}),
        transito=int(d.get("transito", 10)),
        cuenta_como=dict(d.get("cuenta_como") or {}),
        categorias=list(d.get("categorias") or []),
        excluir_categorias=list(d.get("excluir_categorias") or []),
        solo_remoto=bool(d.get("solo_remoto", False)),
        simultaneos=max(1, int(d.get("simultaneos", 1))),
        max_vuelos_dia=d.get("max_vuelos_dia"),
        codigo=str(d.get("codigo", "" if n == 0 else nombre[:1].upper())),
        seccion=str(d.get("seccion", "GRUPOS" if n == 0 else nombre.upper())),
        hoja=str(d.get("hoja", nombre)),
        prefijo_tarea=str(d.get("prefijo_tarea", "P" if n == 0 else nombre[:1].upper() + str(n))),
        tipos=dict(d.get("tipos") or {}),
        principal=bool(d.get("principal", n == 0)),
        nombre_puesto=dict(d.get("nombre_puesto") or {}),
        en_cuadrante=bool(d.get("en_cuadrante", True)),
        puestos_clave=list(d.get("puestos_clave") or d["puestos"][:1]),
    )


def desde_configuracion(datos: dict) -> Operativa:
    op = datos.get("operativa")
    if op:
        recursos = [_recurso(nombre, d, n) for n, (nombre, d) in enumerate(op["recursos"].items())]
        return Operativa(recursos, {k: list(v) for k, v in (op.get("puede_hacer_de") or {}).items()},
                         dict(op.get("coste_falta") or {}))
    return _operativa_azul(datos)


def _operativa_azul(datos: dict) -> Operativa:
    """El perfil de siempre (Azul con Ryanair): un equipo completo hace el vuelo entero y, en
    remoto, una jardinera lleva a los pasajeros."""
    s, j = datos["servicio"], datos["jardineras"]
    equipo = Recurso(
        nombre="Equipo", puestos=list(datos["equipo_plataforma"]), turnos=list(datos["turnos_plataforma"]),
        tareas={"giro": s["giro"], "solo_salida": s["solo_salida"], "solo_llegada": s["solo_llegada"]},
        transito=s["transito_entre_vuelos"],
        cuenta_como={"Carretero": "Operario", "Cintero": "Operario"},
        excluir_categorias=list(CATEGORIAS_APARTE_AZUL), codigo="", seccion="GRUPOS", hoja="Equipos",
        prefijo_tarea="P", principal=True, puestos_clave=["TL", "PB/TOW"])
    jardinera = Recurso(
        nombre="Jardinera", puestos=["Conductor"], turnos=list(datos["turnos_jardineras"]),
        tareas={"llegada": j["llegada"], "salida": j["salida"]}, transito=j["transito"],
        categorias=["Jardinero"], solo_remoto=True, codigo="J", seccion="JARDINERAS", hoja="Jardineras",
        prefijo_tarea="J", tipos={"llegada": "JARDINERA_LLEGADA", "salida": "JARDINERA_SALIDA"},
        # El cuadrante del mes todavía no calcula la demanda de jardineras: mantienen su horario.
        en_cuadrante=False, puestos_clave=[])
    return Operativa([equipo, jardinera], {"Operario": ["TL", "PB/TOW"]},
                     {"TL": 3000, "PB/TOW": 3000, "Operario": 1000})


# --- Tareas de cada vuelo -------------------------------------------------------------------

def _llegada(v: Vuelo, regla: dict) -> tuple[int, int]:
    inicio = v.sta - regla["antes_sta"] if "antes_sta" in regla else v.sta + regla.get("desde_sta", 0)
    fin = v.sta + regla["despues_sta"] if "despues_sta" in regla else v.sta + regla.get("hasta_sta", 0)
    return inicio, fin


def _salida(v: Vuelo, regla: dict) -> tuple[int, int]:
    inicio = v.std - regla.get("antes_std", 0)
    fin = v.std + regla["despues_std"] if "despues_std" in regla else v.std - regla.get("hasta_antes_std", 0)
    return inicio, fin


def tareas_de(recurso: Recurso, vuelos: list[Vuelo]) -> list[Tarea]:
    """Tareas que los vuelos piden a este recurso.

    - `giro` (llegada y salida del mismo avión): una tarea desde `antes_sta` hasta `despues_std`.
      Si el avión pasa más de `suelo_maximo` minutos en tierra (240 si no se dice), se atiende en
      dos veces, con `solo_llegada` y `solo_salida`.
    - `solo_salida` / `solo_llegada`: vuelos que solo salen o solo llegan (y las dos mitades de un
      giro largo).
    - `salida` / `llegada`: una tarea en cada salida o llegada, sea giro o no (un PB que saca
      todas las salidas, una jardinera en cada llegada a remoto…).
    """
    t = recurso.tareas
    p = recurso.prefijo_tarea
    nombre = lambda tipo, por_defecto: recurso.tipos.get(tipo, por_defecto)   # noqa: E731
    resultado = []
    for i, v in enumerate(vuelos):
        if recurso.solo_remoto and not v.remoto:
            continue
        giro, sola_s, sola_l = t.get("giro"), t.get("solo_salida"), t.get("solo_llegada")
        if giro is not None and v.sta is not None and v.std is not None:
            if v.std - v.sta > giro.get("suelo_maximo", 240) and sola_l is not None and sola_s is not None:
                # Mucho tiempo en tierra: el recurso atiende la llegada y vuelve para la salida.
                resultado.append(Tarea(f"{p}{i:03d}L", nombre("solo_llegada", "LLEGADA"), *_llegada(v, sola_l), v))
                resultado.append(Tarea(f"{p}{i:03d}S", nombre("solo_salida", "SALIDA"), *_salida(v, sola_s), v))
            else:
                resultado.append(Tarea(f"{p}{i:03d}", nombre("giro", "GIRO"),
                                       v.sta - giro.get("antes_sta", 0), v.std + giro.get("despues_std", 0), v))
        elif sola_s is not None and v.std is not None and v.sta is None:
            resultado.append(Tarea(f"{p}{i:03d}", nombre("solo_salida", "SALIDA"), *_salida(v, sola_s), v))
        elif sola_l is not None and v.sta is not None and v.std is None:
            resultado.append(Tarea(f"{p}{i:03d}", nombre("solo_llegada", "LLEGADA"), *_llegada(v, sola_l), v))
        if "llegada" in t and v.sta is not None:
            resultado.append(Tarea(f"{p}{i:03d}L", nombre("llegada", "LLEGADA"), *_llegada(v, t["llegada"]), v))
        if "salida" in t and v.std is not None:
            resultado.append(Tarea(f"{p}{i:03d}S", nombre("salida", "SALIDA"), *_salida(v, t["salida"]), v))
    return resultado
