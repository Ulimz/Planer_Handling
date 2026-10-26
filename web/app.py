"""Web sencilla del planificador: subir archivos y descargar resultados.

Arranque: streamlit run web/app.py  (en Windows, doble clic en arrancar_web.bat)
Todo se calcula en este ordenador; los archivos no salen de él.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from planer_handling.configuracion import Configuracion
from planer_handling.desde_cuadrante import generar_parrilla_cuadrante
from planer_handling.importar.ausencias import leer_ausencias
from planer_handling.importar.cuadrante import leer_cuadrante
from planer_handling.importar.parrilla_real import leer_vuelos_parrilla
from planer_handling.importar.vuelos import leer_vuelos
from planer_handling.mensual import aprender_perfiles, dias_del_mes, emparejar_giros, planificar_mes
from planer_handling.mensual_excel import exportar_mes
from planer_handling.parrilla_excel import exportar

RAIZ = Path(__file__).resolve().parent.parent
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

st.set_page_config(page_title="Planificador de handling", page_icon="✈️", layout="wide")
st.title("Planificador de handling")
st.caption("Todo se calcula en este ordenador. Los archivos no se envían a ningún sitio.")


@st.cache_resource
def configuracion() -> Configuracion:
    return Configuracion.cargar(RAIZ / "config" / "base.yaml")


def guardar(subido, carpeta: Path) -> Path:
    ruta = carpeta / subido.name
    ruta.write_bytes(subido.getbuffer())
    return ruta


def elegir_mes(etiqueta: str, por_defecto: date, clave: str) -> tuple[int, int]:
    c1, c2 = st.columns(2)
    mes = c1.selectbox(f"{etiqueta}: mes", range(1, 13), index=por_defecto.month - 1,
                       format_func=lambda m: MESES[m - 1], key=f"{clave}_mes")
    anio = c2.number_input(f"{etiqueta}: año", 2020, 2100, por_defecto.year, key=f"{clave}_anio")
    return int(anio), int(mes)


conf = configuracion()
mensual_tab, diaria_tab = st.tabs(["Cuadrante del mes", "Parrilla del día"])

with mensual_tab:
    st.subheader("Cuadrante del mes a partir de los vuelos")
    st.write("Sube los vuelos del mes y el cuadrante de un mes anterior. El programa continúa la rotación "
             "de cada persona y le pone el horario que mejor cubre los vuelos de cada día.")
    hoy = date.today()
    siguiente = date(hoy.year + hoy.month // 12, hoy.month % 12 + 1, 1)
    anio, mes = elegir_mes("A planificar", siguiente, "plan")
    vuelos_mes = st.file_uploader("Vuelos del mes (Flights, PACOTRON u OMS)", type=["xlsx", "xls", "csv"], key="vm")
    referencia = st.file_uploader("Cuadrante de referencia (normalmente el del mes anterior)", type=["xlsx"], key="ref")
    anio_ref, mes_ref = elegir_mes("Mes del cuadrante de referencia", hoy.replace(day=1), "ref")
    ausencias_archivo = st.file_uploader("Ausencias del mes (opcional): Empleado, Desde, Hasta, Motivo",
                                         type=["xlsx", "csv"], key="aus")
    con_nombres = st.checkbox("Mostrar nombres (si no, solo códigos)", key="nm")
    segundos = st.slider("Tiempo de cálculo por día (segundos)", 5, 60, 20, key="seg")

    if st.button("Generar cuadrante", type="primary", disabled=not (vuelos_mes and referencia)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                ruta_vuelos, ruta_ref = guardar(vuelos_mes, tmp), guardar(referencia, tmp)
                with st.status("Leyendo archivos…") as estado:
                    dias_ref = dias_del_mes(anio_ref, mes_ref)
                    perfiles = aprender_perfiles(leer_cuadrante(ruta_ref, anio_ref), dias_ref, conf)
                    vuelos = {d: leer_vuelos(ruta_vuelos, d, conf.zona_horaria)[0] for d in dias_del_mes(anio, mes)}
                    ausencias = leer_ausencias(guardar(ausencias_archivo, tmp)) if ausencias_archivo else []
                    estado.update(label=f"{len(perfiles)} personas y {sum(map(len, vuelos.values()))} vuelos. "
                                        "Planificando día a día…")
                    barra = st.progress(0.0)
                    cm = planificar_mes(vuelos, perfiles, dias_ref[0], conf, segundos, ausencias,
                                        progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"))
                    salida = tmp / f"cuadrante_{anio}-{mes:02d}.xlsx"
                    exportar_mes(cm, salida, con_nombres)
                    estado.update(label="Cuadrante listo", state="complete")
                st.download_button("Descargar cuadrante", salida.read_bytes(), salida.name, type="primary")
                st.dataframe([{"Día": dp.dia.strftime("%d/%m"), "Vuelos": dp.vuelos, "Personas": len(dp.jornadas),
                               "Ausentes": len(dp.ausentes),
                               "Horas sin cubrir": round(sum(dp.deficit(r) for r in dp.demanda) / 60, 1)}
                              for dp in cm.dias], hide_index=True)
            except Exception as error:  # se enseña al usuario en lugar de una traza
                st.error(f"No se ha podido generar: {error}")

with diaria_tab:
    st.subheader("Parrilla del día a partir del cuadrante")
    st.write("Sube el cuadrante del mes y los vuelos del día. El programa forma los equipos con quien "
             "coincide en horario y les asigna los vuelos.")
    dia = st.date_input("Día", value=date.today(), format="DD/MM/YYYY")
    cuadrante = st.file_uploader("Cuadrante del mes", type=["xlsx"], key="cd")
    vuelos_dia = st.file_uploader("Vuelos (Flights, PACOTRON, OMS o libro de parrillas)",
                                  type=["xlsx", "xls", "csv"], key="vd")
    hoja = st.text_input("Si es un libro de parrillas, nombre de la hoja del día (por ejemplo 15-10)", key="hj")
    con_nombres_dia = st.checkbox("Mostrar nombres (si no, solo códigos)", key="nmd")

    if st.button("Generar parrilla", type="primary", disabled=not (cuadrante and vuelos_dia)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                ruta_vuelos, ruta_cuadrante = guardar(vuelos_dia, tmp), guardar(cuadrante, tmp)
                with st.spinner("Formando equipos y asignando vuelos…"):
                    if hoja:
                        vuelos, incidencias = leer_vuelos_parrilla(ruta_vuelos, hoja, dia)[0], []
                    else:
                        vuelos, incidencias = leer_vuelos(ruta_vuelos, dia, conf.zona_horaria)
                        vuelos = emparejar_giros(vuelos)
                    parrilla = generar_parrilla_cuadrante(dia, vuelos, leer_cuadrante(ruta_cuadrante, dia.year),
                                                          conf, incidencias, 20)
                    salida = tmp / f"parrilla_{dia.isoformat()}.xlsx"
                    exportar(parrilla, salida, conf.equipo_plataforma, con_nombres_dia)
                grupos = [e for e in parrilla.reparto.equipos if e.seccion == "GRUPOS"]
                sin_equipo = sum(1 for t in parrilla.tareas if t.id not in parrilla.asignadas)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Vuelos", len(vuelos))
                c2.metric("Equipos", len(grupos))
                c3.metric("De refuerzo", len(parrilla.reparto.equipos) - len(grupos))
                c4.metric("Sin equipo", sin_equipo)
                st.download_button("Descargar parrilla", salida.read_bytes(), salida.name, type="primary")
                pendientes = [i for i in parrilla.incidencias if i.gravedad == "PENDIENTE"]
                if pendientes:
                    st.warning(f"{len(pendientes)} incidencias pendientes (detalle en la hoja Incidencias).")
            except Exception as error:
                st.error(f"No se ha podido generar: {error}")
