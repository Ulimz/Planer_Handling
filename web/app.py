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
from planer_handling.mensual import aprender_perfiles, dias_del_mes, emparejar_giros, planificar_mes, reorganizar
from planer_handling.mensual_excel import exportar_mes
from planer_handling.parrilla_excel import exportar
from planer_handling.registro import Almacen, motivos

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


def leer_vuelos_mes(ruta: Path, dias: list[date]) -> dict:
    return {d: v for d in dias if (v := emparejar_giros(leer_vuelos(ruta, d, conf.zona_horaria)[0]))}


conf = configuracion()
almacen = Almacen(RAIZ / "datos" / "registro")
colores = motivos(conf)
ausencias_tab, mensual_tab, diaria_tab = st.tabs(["Plantilla y ausencias", "Cuadrante del mes", "Parrilla del día"])

with ausencias_tab:
    st.subheader("Bajas, vacaciones, sanciones y permisos")
    st.write("Lo que apuntes aquí lo tienen en cuenta solos el cuadrante del mes y la parrilla del día. "
             "Se guarda en este ordenador, en la carpeta datos/registro.")

    plantilla = almacen.plantilla()
    with st.expander(f"Plantilla: {len(plantilla)} personas" if plantilla else "Plantilla: aún no cargada",
                     expanded=not plantilla):
        st.write("Sube un cuadrante para sacar de él la lista de personas. Vuelve a subirlo cuando entre o salga gente.")
        cuadrante_plantilla = st.file_uploader("Cuadrante", type=["xlsx"], key="pl")
        if st.button("Guardar plantilla", disabled=not cuadrante_plantilla):
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    n = almacen.guardar_plantilla(leer_cuadrante(guardar(cuadrante_plantilla, Path(tmp)), date.today().year))
                    st.success(f"Plantilla guardada: {n} personas.")
                    st.rerun()
                except Exception as error:
                    st.error(f"No se ha podido leer el cuadrante: {error}")

    st.markdown("#### Apuntar una ausencia")
    if not plantilla:
        st.info("Primero carga la plantilla.")
    else:
        with st.form("nueva", clear_on_submit=True):
            persona = st.selectbox("Persona", plantilla, format_func=lambda p: f"{p[0]} ({p[1]})", index=None,
                                   placeholder="Escribe para buscar")
            motivo = st.selectbox("Motivo", list(colores))
            c1, c2, c3 = st.columns(3)
            desde = c1.date_input("Desde", value=date.today(), format="DD/MM/YYYY")
            abierta = c3.checkbox("Sin fecha de fin (hasta que le den el alta)", value=True)
            hasta = c2.date_input("Hasta (incluido)", value=date.today(), format="DD/MM/YYYY")
            nota = st.text_input("Nota (opcional)")
            if st.form_submit_button("Apuntar", type="primary"):
                if persona is None:
                    st.error("Elige una persona.")
                else:
                    try:
                        almacen.anadir(persona[0], persona[1], motivo, desde, None if abierta else hasta, nota)
                        st.success(f"Apuntado: {persona[0]}, {motivo.lower()}.")
                    except ValueError as error:
                        st.error(str(error))

    registros = almacen.registros()
    hoy = date.today()
    fuera_hoy = [r for r in registros if r.activa(hoy)]
    abiertas = [r for r in registros if r.abierta]
    st.markdown(f"#### Pendientes de alta: {len(abiertas)}")
    st.caption(f"Hoy hay {len(fuera_hoy)} personas fuera. Para las que tienen fecha de fin no hace falta dar el alta.")
    for r in sorted(abiertas, key=lambda r: r.desde):
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.write(f"**{r.empleado}** ({r.funcion}): {r.motivo.lower()} desde el {r.desde:%d/%m/%Y}"
                 + (f". {r.nota}" if r.nota else ""))
        alta = c2.date_input("Día que vuelve", value=hoy, format="DD/MM/YYYY", key=f"alta_{r.id}",
                             label_visibility="collapsed")
        if c3.button("Dar alta", key=f"btn_{r.id}"):
            try:
                almacen.dar_alta(r.id, alta)
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    with st.expander(f"Todas las ausencias apuntadas ({len(registros)})"):
        if registros:
            st.dataframe([{"Persona": r.empleado, "Función": r.funcion, "Motivo": r.motivo,
                           "Desde": r.desde.strftime("%d/%m/%Y"),
                           "Hasta": r.hasta.strftime("%d/%m/%Y") if r.hasta else "abierta", "Nota": r.nota}
                          for r in sorted(registros, key=lambda r: r.desde, reverse=True)], hide_index=True)
            a_borrar = st.selectbox("Borrar una apuntada por error", registros, index=None,
                                    format_func=lambda r: f"{r.empleado}, {r.motivo.lower()}, {r.desde:%d/%m/%Y}")
            if st.button("Borrar", disabled=a_borrar is None):
                almacen.borrar(a_borrar.id)
                st.rerun()

    st.markdown("#### Reorganizar el cuadrante para cubrir a quien falta")
    st.write("Sube el cuadrante publicado y los vuelos del mes. El programa cambia el horario a las menos "
             "personas posibles para cubrir los huecos, y te da la lista de cambios para avisarles.")
    anio_r, mes_r = elegir_mes("Mes del cuadrante", hoy.replace(day=1), "reo")
    cuadrante_r = st.file_uploader("Cuadrante publicado", type=["xlsx"], key="cr")
    vuelos_r = st.file_uploader("Vuelos del mes (Flights, PACOTRON u OMS)", type=["xlsx", "xls", "csv"], key="vr")
    dias_r = dias_del_mes(anio_r, mes_r)
    rango = st.date_input("Días a reorganizar", value=(max(hoy, dias_r[0]) if hoy <= dias_r[-1] else dias_r[0],
                                                         min(dias_r[-1], date.fromordinal(max(hoy, dias_r[0]).toordinal() + 6))),
                          min_value=dias_r[0], max_value=dias_r[-1], format="DD/MM/YYYY", key="rango")
    con_nombres_r = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nmr")
    if st.button("Reorganizar", type="primary", disabled=not (cuadrante_r and vuelos_r and len(rango) == 2)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                with st.status("Leyendo archivos…") as estado:
                    filas = leer_cuadrante(guardar(cuadrante_r, tmp), anio_r)
                    elegidos = [d for d in dias_r if rango[0] <= d <= rango[1]]
                    vuelos = leer_vuelos_mes(guardar(vuelos_r, tmp), elegidos)
                    estado.update(label=f"{len(filas)} personas y {sum(map(len, vuelos.values()))} vuelos. "
                                        "Reorganizando día a día…")
                    barra = st.progress(0.0)
                    cm, cambios = reorganizar(filas, dias_r, vuelos, almacen.ausencias(), conf, 20,
                                              progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"))
                    salida = tmp / f"cuadrante_reorganizado_{anio_r}-{mes_r:02d}.xlsx"
                    exportar_mes(cm, salida, con_nombres_r, colores, cambios)
                    estado.update(label="Reorganización lista", state="complete")
                st.download_button("Descargar cuadrante reorganizado", salida.read_bytes(), salida.name, type="primary")
                if cambios:
                    st.dataframe([{"Día": c.dia.strftime("%d/%m"), "Persona": c.empleado, "Función": c.funcion,
                                   "Antes": c.antes, "Ahora": c.despues, "Cambio": c.tipo}
                                  for c in sorted(cambios, key=lambda c: (c.dia, c.tipo))], hide_index=True)
                else:
                    st.info("No hace falta cambiar nada en esos días.")
            except Exception as error:
                st.error(f"No se ha podido reorganizar: {error}")

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
    st.caption("Las ausencias apuntadas en la pestaña Plantilla y ausencias se tienen en cuenta solas.")
    con_nombres = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nm")
    segundos = st.slider("Tiempo de cálculo por día (segundos)", 10, 60, 30, key="seg")

    if st.button("Generar cuadrante", type="primary", disabled=not (vuelos_mes and referencia)):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            try:
                ruta_vuelos, ruta_ref = guardar(vuelos_mes, tmp), guardar(referencia, tmp)
                with st.status("Leyendo archivos…") as estado:
                    dias_ref = dias_del_mes(anio_ref, mes_ref)
                    perfiles = aprender_perfiles(leer_cuadrante(ruta_ref, anio_ref), dias_ref, conf)
                    vuelos = {d: leer_vuelos(ruta_vuelos, d, conf.zona_horaria)[0] for d in dias_del_mes(anio, mes)}
                    ausencias = almacen.ausencias()
                    if ausencias_archivo:
                        ausencias += leer_ausencias(guardar(ausencias_archivo, tmp))
                    estado.update(label=f"{len(perfiles)} personas y {sum(map(len, vuelos.values()))} vuelos. "
                                        "Planificando día a día…")
                    barra = st.progress(0.0)
                    cm = planificar_mes(vuelos, perfiles, dias_ref[0], conf, segundos, ausencias,
                                        progreso=lambda d, hechos, total: barra.progress(hechos / total, f"{d:%d/%m}"))
                    salida = tmp / f"cuadrante_{anio}-{mes:02d}.xlsx"
                    exportar_mes(cm, salida, con_nombres, colores)
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
    con_nombres_dia = st.checkbox("Mostrar nombres (si no, solo códigos)", value=True, key="nmd")

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
                                                          conf, incidencias, 20, almacen.ausencias())
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
