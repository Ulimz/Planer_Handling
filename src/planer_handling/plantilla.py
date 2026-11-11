"""Ficha de plantilla: lo que el programa necesita saber de cada persona para hacerle el horario sin
partir de turnos de nadie. Una fila por código (nunca nombres): función, contrato, rotación y grupo,
turnos del ciclo, horas al año, hora de entrada habitual y si hace partidos.

La ficha se aprende una vez de todos los cuadrantes guardados (`aprender`): ahí se ve en qué grupo
de rotación va cada uno, a qué hora suele entrar de mañana y de tarde y si hace partidos. Después se
edita a mano cuando alguien entra, sale o cambia.

Con la ficha y los vuelos el programa hace el mes:
- Todos trabajan los días que les toca su rotación (6x3, 4x4…) según su grupo y la fecha de inicio de
  los ciclos (`inicio_ciclos` en la config). La rotación sigue de un año a otro, no se reinicia.
- El turno (mañana o tarde) de cada día del ciclo sale de la rotación (`fases`), y la hora exacta y
  las horas del día, de los vuelos. Los parciales y discontinuos hacen jornadas de 2 a 8 h según su
  contrato, sin pasar de sus horas al año repartidas en lo que queda de año.
- Quien no tiene rotación se llama según los vuelos, con el descanso semanal mínimo.
- Las horas hechas en los meses guardados (real si lo hay; si no, el del programa) se descuentan
  (ver `cuenta_anual`).
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path

from .configuracion import Configuracion
from .importar.cuadrante import FilaCuadrante
from .importar.habilitaciones import Ficha, aplicar, clave_persona
from .mensual import MEDIODIA, PASO, Perfil, dias_del_mes
from .modelos import Empleado, Habilitacion, hhmm

ARCHIVO = "plantilla.json"
DESCANSO_SEMANAL_DIAS = 1.5     # Estatuto art. 37.1: día y medio de descanso a la semana como mínimo
AJUSTE_ROTACION = 0.8           # por debajo de este encaje con su grupo, la ficha avisa para revisarla
DIAS_RECIENTES = 60             # si el año entero no encaja (cambió de grupo), se mira lo último
PARTIDOS_MINIMO = 0.2           # hace partidos si al menos 1 de cada 5 jornadas lo es
COMPLETOS = ("TC", "TCC")       # contratos de jornada completa (las horas al año son las del convenio)
COLUMNAS = {                    # nombre en pantalla de cada campo
    "codigo": "Código", "funcion": "Función", "contrato": "Contrato", "rotacion": "Rotación",
    "grupo": "Grupo", "fases": "Turnos del ciclo", "horas_anuales": "Horas al año (contrato)",
    "habitual": "Entrada habitual", "entrada": "Entrada fija", "partido": "Partido", "activo": "Activo",
}


@dataclass
class Persona:
    codigo: str
    funcion: str
    contrato: str = ""
    rotacion: str = ""            # "6x3", "4x4"… (de `rotaciones` en la config); vacío = sin rotación
    grupo: str = ""               # "1", "2", "3"… (de la config); o un número de días de desfase
    fases: str = ""               # turno de cada día de trabajo: "MMMTTT"; vacío = el de su rotación
    horas_anuales: float = 0      # horas de su contrato al año; 0 = jornada completa
    habitual: str = ""            # "04:45/18:00": hora a la que suele entrar de mañana / de tarde
    entrada: str = ""             # "05:00" (o "05:00/15:00"): concreción horaria, entra siempre a esa hora
    partido: str = ""             # "3+3": si hace partidos, horas de cada tramo
    activo: bool = True


# --- guardar y leer --------------------------------------------------------------------------

def guardar(carpeta: str | Path, personas: list[Persona]) -> None:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / ARCHIVO).write_text(json.dumps([asdict(p) for p in personas], ensure_ascii=False), encoding="utf-8")


def leer(carpeta: str | Path) -> list[Persona] | None:
    ruta = Path(carpeta) / ARCHIVO
    if not ruta.exists():
        return None
    nombres = {f.name for f in fields(Persona)}
    return [Persona(**{k: v for k, v in x.items() if k in nombres}) for x in json.loads(ruta.read_text(encoding="utf-8"))]


def tabla(personas: list[Persona]) -> list[dict]:
    return [{COLUMNAS[k]: v for k, v in asdict(p).items()} for p in personas]


def desde_tabla(registros: list[dict]) -> tuple[list[Persona], list[str]]:
    """Lo contrario de `tabla`. Devuelve también los errores (filas sin código, códigos repetidos…)."""
    inverso = {v: k for k, v in COLUMNAS.items()}
    personas, errores, vistos = [], [], set()
    for n, fila in enumerate(registros, 1):
        x = {inverso[k]: v for k, v in fila.items() if k in inverso}
        texto = {k: "" if v is None else str(v).strip() for k, v in x.items() if k not in ("activo", "horas_anuales")}
        codigo = texto.get("codigo", "")
        if not codigo:
            if any(texto.values()):
                errores.append(f"Fila {n}: falta el código.")
            continue
        if codigo in vistos:
            errores.append(f"{codigo}: está repetido.")
            continue
        vistos.add(codigo)
        try:
            horas = float(x.get("horas_anuales") or 0)
        except (TypeError, ValueError):
            errores.append(f"{codigo}: las horas al año deben ser un número.")
            horas = 0
        fases = texto.get("fases", "").upper().replace(" ", "")
        if set(fases) - {"M", "T"}:
            errores.append(f"{codigo}: en los turnos del ciclo solo valen M y T (ej. MMMTTT).")
            fases = ""
        for campo, nombre in (("habitual", "entrada habitual"), ("entrada", "entrada fija")):
            if texto.get(campo) and _entradas(texto[campo]) is None:
                errores.append(f"{codigo}: la {nombre} debe ser una hora (05:00) o dos (05:00/15:00).")
                texto[campo] = ""
        if texto.get("partido") and _partido(texto["partido"]) is None:
            errores.append(f"{codigo}: el partido se escribe con las horas de cada tramo, como 3+3.")
            texto["partido"] = ""
        activo = x.get("activo")
        personas.append(Persona(codigo, texto.get("funcion", ""), texto.get("contrato", ""), texto.get("rotacion", ""),
                                texto.get("grupo", ""), fases, horas, texto.get("habitual", ""),
                                texto.get("entrada", ""), texto.get("partido", ""),
                                True if activo is None else bool(activo)))
    return personas, errores


def _entradas(texto: str) -> list[int] | None:
    resultado = []
    for parte in texto.replace(" ", "").split("/"):
        try:
            h, m = (parte.split(":") + ["0"])[:2]
            h, m = int(h), int(m)
        except ValueError:
            return None
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        resultado.append(h * 60 + m)
    return resultado if 1 <= len(resultado) <= 2 else None


def _partido(texto: str) -> tuple[int, int] | None:
    try:
        a, b = (float(x.replace(",", ".")) for x in texto.replace(" ", "").split("+"))
    except ValueError:
        return None
    return (int(a * 60), int(b * 60)) if 1 <= a <= 8 and 1 <= b <= 8 else None


def _horas(minutos: float) -> str:
    h = round(minutos / 30) / 2
    return f"{h:g}".replace(".", ",")


# --- revisar la ficha con la config ------------------------------------------------------------

def revisar(personas: list[Persona], conf: Configuracion) -> list[str]:
    """Avisos de lo que no encaja con la configuración de la empresa."""
    rotaciones = conf.datos.get("rotaciones", {})
    contratos = conf.datos.get("contratos", {})
    funciones = conf.datos.get("funciones", {})
    avisos = []
    for p in personas:
        if not p.activo:
            continue
        if p.funcion not in funciones:
            avisos.append(f"{p.codigo}: la función '{p.funcion}' no está en la configuración.")
        if p.contrato and p.contrato not in contratos:
            avisos.append(f"{p.codigo}: el contrato '{p.contrato}' no está en la configuración.")
        if p.rotacion:
            regla = rotaciones.get(p.rotacion)
            if regla is None:
                avisos.append(f"{p.codigo}: la rotación '{p.rotacion}' no está en la configuración.")
            elif _desfase_grupo(p, regla) is None:
                avisos.append(f"{p.codigo}: falta el grupo de su rotación {p.rotacion} "
                              f"({', '.join(map(str, regla.get('grupos', {}))) or 'un número de días'}).")
            elif p.fases and len(p.fases) != regla["trabajo"]:
                avisos.append(f"{p.codigo}: los turnos del ciclo deben ser {regla['trabajo']} letras (M/T).")
    return avisos


def _desfase_grupo(p: Persona, regla: dict) -> int | None:
    grupos = {str(k): v for k, v in regla.get("grupos", {}).items()}
    if p.grupo in grupos:
        return int(grupos[p.grupo])
    try:
        return int(p.grupo)
    except ValueError:
        return None


# --- aprender la ficha de los cuadrantes guardados -------------------------------------------------

def _inicio_ciclos(conf: Configuracion) -> date:
    valor = conf.datos.get("inicio_ciclos")
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor))


def _encaje(activos: set[date], dias: list[date], trabajo: int, ciclo: int, desfase: int, inicio: date) -> float:
    return sum((d in activos) == (((d - inicio).days + desfase) % ciclo < trabajo) for d in dias) / len(dias)


def _rotaciones_de(funcion: str, conf: Configuracion) -> dict[str, dict]:
    """Las rotaciones que puede llevar una función: las que la nombran en `funciones` o, si ninguna la
    nombra, las que no tienen `funciones` (en Azul, la 4x4 es solo de RCO y ARCO)."""
    rotaciones = {n: r for n, r in conf.datos.get("rotaciones", {}).items() if r.get("grupos")}
    suyas = {n: r for n, r in rotaciones.items() if funcion in (r.get("funciones") or [])}
    return suyas or {n: r for n, r in rotaciones.items() if not r.get("funciones")}


def _mejor_grupo(activos: set[date], dias: list[date], conf: Configuracion,
                 funcion: str = "") -> tuple[str, int, float] | None:
    """(rotación, desfase, encaje) del grupo que mejor explica los días que la persona estaba en el
    cuadrante (trabajando o con ausencia marcada, que también son días de su rotación)."""
    inicio = _inicio_ciclos(conf)
    mejor = None
    for nombre, regla in _rotaciones_de(funcion, conf).items():
        ciclo = regla["trabajo"] + regla["libre"]
        for desfase in sorted({int(v) % ciclo for v in regla["grupos"].values()}):
            encaje = _encaje(activos, dias, regla["trabajo"], ciclo, desfase, inicio)
            if mejor is None or encaje > mejor[2]:
                mejor = (nombre, desfase, encaje)
    return mejor


def aprender(meses: list[tuple[list[FilaCuadrante], list[date]]], conf: Configuracion,
             contratos: dict[str, str] | None = None) -> tuple[list[Persona], dict]:
    """Ficha de cada código a partir de todos los cuadrantes guardados (los más recientes, al final).
    Devuelve también un resumen de lo aprendido para enseñarlo en pantalla."""
    rotaciones = conf.datos.get("rotaciones", {})
    reglas_contrato = conf.datos.get("contratos", {})
    inicio = _inicio_ciclos(conf)
    todos = sorted({d for _, dias in meses for d in dias})
    jornadas: dict[str, dict] = {}
    ausente: dict[str, set] = {}
    funcion: dict[str, str] = {}
    for filas, dias in meses:
        for f in filas:
            jornadas.setdefault(f.nombre, {}).update({d: j for d, j in f.jornadas.items() if j.tramos})
            ausente.setdefault(f.nombre, set()).update(f.marcas_vacias)
            if f.funcion:
                funcion[f.nombre] = f.funcion
    personas, encajes = [], []
    resumen = Counter()
    for codigo, suyas in jornadas.items():
        activos = set(suyas) | ausente.get(codigo, set())
        if not suyas:
            continue
        contrato = (contratos or {}).get(codigo, "")
        p = Persona(codigo, funcion.get(codigo, ""), contrato)
        dias = [d for d in todos if min(activos) <= d <= max(activos)]
        mejor = _mejor_grupo(activos, dias, conf, p.funcion) if len(dias) >= 14 else None
        if mejor and mejor[2] < AJUSTE_ROTACION:
            # Puede que cambiara de grupo: se mira solo lo último. Todos van en una rotación (también
            # parciales, discontinuos y eventuales); si ni así encaja bien, se le da la que más se
            # parece y se avisa para revisarla.
            reciente = _mejor_grupo(activos, dias[-DIAS_RECIENTES:], conf, p.funcion)
            if reciente and reciente[2] >= mejor[2]:
                mejor = reciente
            if mejor[2] < AJUSTE_ROTACION:
                resumen["a revisar (encaja poco con su grupo)"] += 1
        if mejor:
            nombre, desfase, encaje = mejor
            regla = rotaciones[nombre]
            ciclo = regla["trabajo"] + regla["libre"]
            p.rotacion = nombre
            p.grupo = next((str(g) for g, v in regla["grupos"].items() if int(v) % ciclo == desfase), str(desfase))
            encajes.append(encaje)
            # Turnos del ciclo: solo si no son los de la rotación.
            por_pos: dict[int, Counter] = {}
            for d, j in suyas.items():
                pos = ((d - inicio).days + desfase) % ciclo
                if pos < regla["trabajo"]:
                    por_pos.setdefault(pos, Counter())["M" if j.tramos[0][0] < MEDIODIA else "T"] += 1
            fases = "".join(por_pos[i].most_common(1)[0][0] if i in por_pos else "?" for i in range(regla["trabajo"]))
            if "?" not in fases and fases != str(regla.get("fases") or fases):
                p.fases = fases
            resumen[f"{nombre} grupo {p.grupo}"] += 1
        else:
            resumen["sin rotación"] += 1
        # Hora a la que suele entrar de mañana y de tarde.
        entradas = {"M": [], "T": []}
        partidos = []
        for j in suyas.values():
            entradas["M" if j.tramos[0][0] < MEDIODIA else "T"].append(j.tramos[0][0])
            if len(j.tramos) == 2:
                partidos.append((j.tramos[0][1] - j.tramos[0][0], j.tramos[1][1] - j.tramos[1][0]))
        habitual = {f: Counter(x).most_common(1)[0][0] for f, x in entradas.items() if x}
        p.habitual = "/".join(hhmm(habitual[f]) for f in ("M", "T") if f in habitual)
        if len(habitual) == 1 and "T" in habitual:
            p.habitual = "/" + p.habitual
        if partidos and len(partidos) >= PARTIDOS_MINIMO * len(suyas):
            p.partido = "+".join(_horas(statistics.median(x[k] for x in partidos)) for k in range(2))
        if reglas_contrato.get(contrato, {}).get("horario_fijo"):
            p.entrada, p.habitual = p.habitual.lstrip("/"), ""
        # Horas al año de quien no es de jornada completa: lo que hace de verdad, pasado a un año.
        if contrato not in COMPLETOS and len(dias) >= 28:
            minutos = sum(fin - ini for j in suyas.values() for ini, fin in j.tramos)
            anuales = round(minutos / 60 * 365 / len(dias) / 10) * 10
            if not (contrato == "" and anuales >= 0.95 * horas_completa(conf)):
                p.horas_anuales = anuales
        personas.append(p)
    personas.sort(key=lambda x: x.codigo)
    info = {"personas": len(personas), "meses": len(meses),
            "encaje_medio": round(statistics.mean(encajes), 3) if encajes else 0,
            "grupos": dict(sorted(resumen.items()))}
    return personas, info


def desde_cuadrante(filas: list[FilaCuadrante], dias: list[date], conf: Configuracion,
                    contratos: dict[str, str] | None = None) -> list[Persona]:
    return aprender([(filas, dias)], conf, contratos)[0]


# --- horas del año -------------------------------------------------------------------------------

def horas_completa(conf: Configuracion) -> float:
    return float(conf.datos.get("horas_anuales_completa", 0) or 0)


def horas_objetivo(p: Persona, conf: Configuracion) -> float:
    """Horas al año de su contrato: las de su ficha o, si no tiene, las de jornada completa."""
    return p.horas_anuales or horas_completa(conf)


def horas_tope(p: Persona, conf: Configuracion) -> float:
    """Lo más que puede hacer al año: el máximo de su contrato en el convenio (`horas_anuales` de
    `contratos` en la config; en Azul, el 90 % para un parcial), y nunca menos que las de su contrato."""
    regla = conf.datos.get("contratos", {}).get(p.contrato, {})
    maximo = float((regla.get("horas_anuales") or [0, 0])[-1] or horas_completa(conf))
    return max(maximo, p.horas_anuales or 0)


def horas_por_codigo(filas: list[FilaCuadrante] | None) -> dict[str, float]:
    resultado: dict[str, float] = {}
    for f in filas or []:
        minutos = sum(fin - ini for j in f.jornadas.values() for ini, fin in j.tramos)
        resultado[f.nombre] = resultado.get(f.nombre, 0) + minutos / 60
    return resultado


def horas_hechas(archivo, anio: int, hasta_mes: int) -> tuple[dict[str, float], set[int]]:
    """Horas de cada código en los meses del año anteriores a `hasta_mes`, y qué meses tienen datos
    (cuenta el real si está; si no, el del programa). Los meses sin nada guardado no cuentan."""
    total: dict[str, float] = {}
    meses = set()
    for mes in range(1, hasta_mes):
        for tipo in ("real", "programa"):
            filas = archivo.cuadrante(anio, mes, tipo)
            if filas:
                for codigo, h in horas_por_codigo(filas).items():
                    total[codigo] = total.get(codigo, 0) + h
                meses.add(mes)
                break
    return total, meses


def objetivo_del_mes(p: Persona, conf: Configuracion, anio: int, mes: int, hechas: float = 0,
                     meses_con_dato: set[int] | frozenset = frozenset(), tope: bool = True) -> float:
    """Horas que le tocan este mes (con `tope`, las que como mucho puede hacer): lo que le queda del año
    repartido por días entre lo que falta. En los meses anteriores sin datos guardados se supone que
    hizo su parte proporcional."""
    total = horas_tope(p, conf) if tope else horas_objetivo(p, conf)
    if not total:
        return 0
    dias_anio = (date(anio + 1, 1, 1) - date(anio, 1, 1)).days
    sin_dato = sum(len(dias_del_mes(anio, m)) for m in range(1, mes) if m not in meses_con_dato)
    quedan = max(0.0, total - hechas - total * sin_dato / dias_anio)
    return quedan * len(dias_del_mes(anio, mes)) / (date(anio + 1, 1, 1) - date(anio, mes, 1)).days


def cuenta_anual(personas: list[Persona], archivo, conf: Configuracion, anio: int, mes: int,
                 previstas: dict[str, float] | None = None) -> list[dict]:
    """Tabla para pantalla: horas al año, hechas antes de este mes, las que le tocan y el máximo, y con
    `previstas` (las del cuadrante del mes), lo que le quedaría para el resto del año."""
    hechas, meses = horas_hechas(archivo, anio, mes)
    filas = []
    for p in personas:
        if not p.activo:
            continue
        total = horas_objetivo(p, conf)
        h = hechas.get(p.codigo, 0)
        fila = {"Código": p.codigo, "Función": p.funcion, "Contrato": p.contrato or "—",
                "Rotación": f"{p.rotacion} {p.grupo}".strip() or "—", "Horas al año": round(total),
                "Máximo al año": round(horas_tope(p, conf)), "Hechas antes": round(h, 1),
                "Le tocan este mes": round(objetivo_del_mes(p, conf, anio, mes, h, meses, tope=False), 1),
                "Máximo este mes": round(objetivo_del_mes(p, conf, anio, mes, h, meses), 1)}
        if previstas is not None:
            prev = previstas.get(p.codigo, 0)
            fila["Previstas este mes"] = round(prev, 1)
            fila["Quedan para el resto del año"] = round(total - h - prev, 1)
        filas.append(fila)
    return filas


# --- de la ficha a los perfiles que usa el planificador ---------------------------------------

def _hora_turno(conf: Configuracion, nombre: str) -> int | None:
    turno = conf.datos.get("turnos", {}).get(nombre)
    if not turno:
        return None
    h, m = str(turno["inicio"]).split(":")
    return int(h) * 60 + int(m)


def _horas_m_t(texto: str) -> tuple[int | None, int | None]:
    """"04:45/18:00" -> (285, 1080); "05:00" -> (300, None); "/18:00" -> (None, 1080)."""
    if not texto:
        return None, None
    partes = texto.split("/")
    m = _entradas(partes[0]) if partes[0].strip() else None
    t = _entradas(partes[1]) if len(partes) > 1 and partes[1].strip() else None
    m, t = (m or [None])[0], (t or [None])[0]
    if m is not None and m >= MEDIODIA and t is None:
        m, t = None, m
    return m, t


def perfiles(personas: list[Persona], conf: Configuracion, anio: int, mes: int,
             formacion: dict[str, Ficha] | None = None, hechas: dict[str, float] | None = None,
             meses_con_dato: set[int] | frozenset = frozenset()) -> tuple[list[Perfil], list[str]]:
    """Perfiles para `planificar_mes` (con referencia = día 1 del mes) sacados solo de la ficha."""
    rotaciones = conf.datos.get("rotaciones", {})
    reglas_contrato = conf.datos.get("contratos", {})
    funciones = conf.datos.get("funciones", {})
    referencia = date(anio, mes, 1)
    dias_mes = len(dias_del_mes(anio, mes))
    inicio = _inicio_ciclos(conf)
    completa = horas_completa(conf)
    avisos = revisar(personas, conf)
    resultado = []
    for p in personas:
        if not p.activo:
            continue
        regla_f = funciones.get(p.funcion) or {"categoria": "Operario", "habilitaciones": ["Operario"]}
        habilitaciones = aplicar([Habilitacion(h) for h in regla_f["habilitaciones"]],
                                 (formacion or {}).get(clave_persona(p.codigo)))
        empleado = Empleado(id=p.codigo, categoria=regla_f["categoria"], contrato=p.funcion,
                            rotacion=f"{p.rotacion}-{p.grupo}" if p.rotacion else "",
                            habilitaciones=habilitaciones, nombre=p.codigo)
        regla_c = reglas_contrato.get(p.contrato, {})
        regla_r = rotaciones.get(p.rotacion) if p.rotacion else None
        mando = regla_f["categoria"] == "Mando intermedio"
        fija_m, fija_t = _horas_m_t(p.entrada)
        hab_m, hab_t = _horas_m_t(p.habitual)
        m = next(x for x in (fija_m, hab_m, _hora_turno(conf, "MM" if mando else "M"), 5 * 60) if x is not None)
        t = next(x for x in (fija_t, hab_t, _hora_turno(conf, "MT" if mando else "T"), 13 * 60) if x is not None)
        if p.entrada and fija_m is None:
            m = t
        elif p.entrada and fija_t is None:
            t = m
        perfil = Perfil(empleado, p.funcion, "irregular", contrato=p.contrato,
                        inicio_habitual={"M": m, "T": t, "": m})
        # Duración de la jornada: la de su rotación (mandos 10 h) o la de su contrato.
        jornadas = [int(h * 60) for h in (regla_r or {}).get("jornadas_h") or regla_c.get("jornadas_h") or [8]]
        perfil.duracion = max(jornadas)
        perfil.horario_fijo = bool(regla_c.get("horario_fijo") or p.entrada)
        if len(jornadas) > 1 and not perfil.horario_fijo:
            perfil.duraciones = jornadas
            perfil.jornada_minima = min(jornadas)
            if regla_r and p.horas_anuales:
                # Para que haga sus horas del contrato: cada día de su rotación, al menos una parte
                # (`jornada_minima_respecto_referencia`) de su jornada media.
                media = p.horas_anuales * 60 / (365 * regla_r["trabajo"] / (regla_r["trabajo"] + regla_r["libre"]))
                minima = int(conf.datos.get("jornada_minima_respecto_referencia", 0.8) * media) // PASO * PASO
                perfil.jornada_minima = min(max(jornadas), max(min(jornadas), minima))
        if p.partido and not perfil.horario_fijo:
            a, b = _partido(p.partido)
            perfil.partido = (a, 0, b)
        perfil.horas_mes = list(regla_c.get("horas_mes") or [])
        desfase = _desfase_grupo(p, regla_r) if regla_r else None
        if regla_r and desfase is not None:
            ciclo = regla_r["trabajo"] + regla_r["libre"]
            perfil.patron = p.rotacion
            perfil.ciclo_dias = (regla_r["trabajo"], regla_r["libre"])
            perfil.desfase = ((referencia - inicio).days + desfase) % ciclo
            fases = p.fases or str(regla_r.get("fases") or "")
            perfil.fases = {i: f for i, f in enumerate(fases) if f in "MT"}
            perfil.dias_referencia = dias_mes
        else:
            # Sin rotación: se le llama según los vuelos, con el descanso semanal mínimo.
            perfil.dias_referencia = dias_mes - math.ceil(dias_mes * DESCANSO_SEMANAL_DIAS / 7)
        # Tope de horas del mes para quien no es de jornada completa (lo que le queda del año).
        total = horas_tope(p, conf)
        if total and (total < completa or not regla_r):
            objetivo = objetivo_del_mes(p, conf, anio, mes, (hechas or {}).get(p.codigo, 0), meses_con_dato)
            perfil.minutos_objetivo = max(PASO, int(objetivo * 60) // PASO * PASO)
        perfil.minutos_referencia = perfil.minutos_objetivo or perfil.duracion * perfil.dias_referencia
        resultado.append(perfil)
    return resultado, avisos
