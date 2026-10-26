# Planer Handling

Motor de planificación de personal de handling en tierra. A partir de la programación de vuelos y de la plantilla, genera la parrilla de un día: qué personal trabaja, cómo se forman los equipos de plataforma y qué vuelos atiende cada equipo y cada jardinera.

Es la evolución de PARRITRON: en lugar de revisar una parrilla hecha a mano, la genera automáticamente con los mismos formatos de entrada y aplica comprobaciones parecidas.

## Qué hace hoy (MVP)

1. **Lee los vuelos** en formato PACOTRON u OMS (Excel o CSV), pasa la hora Zulu a hora local de la base y detecta filas incompletas o repetidas.
2. **Calcula quién trabaja ese día** según su rotación (6x3, 4x4) o, para contratos sin rotación fija, un patrón 5x2, respetando fechas de llamamiento y de alta.
3. **Calcula cuántos equipos hacen falta por turno** (mañana, intermedio, tarde y cierre) con OR-Tools, a partir del pico de vuelos simultáneos.
4. **Forma los equipos de plataforma** (TL, PB/TOW, carretero, cintero y operario) con personal que tenga la habilitación vigente, y reparte jardineros, hipódromo, mandos intermedios y parciales.
5. **Asigna cada vuelo a un equipo** y cada vuelo en remoto a una jardinera con OR-Tools CP-SAT, sin solapes y dejando tiempo de tránsito entre vuelos.
6. **Valida el resultado** (vuelos sin equipo, equipos incompletos, habilitaciones a punto de caducar…) y exporta un Excel con resumen, equipos, vuelos, jardineras, personal, incidencias y un Gantt.

## Uso

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Datos ficticios de ejemplo (ya incluidos en ejemplos/)
python scripts/generar_vuelos_ficticios.py
python scripts/generar_plantilla_ficticia.py --escala 2

planer --fecha 2027-07-15 --vuelos ejemplos/vuelos_ficticios.xlsx --plantilla ejemplos/plantilla_ficticia.xlsx
```

Con el horario real de cada persona (cuadrante mensual) y los vuelos de una parrilla diaria ya hecha:

```bash
planer --fecha 2025-02-06 --cuadrante datos/Turnos_Febrero.xlsx --vuelos datos/parrillas.xlsx --hoja 29-10
```

En este modo cada TL disponible abre un equipo con su horario, el resto de puestos se cubre con quien más coincide con él (los turnos partidos cuentan como dos tramos) y las funciones del cuadrante (TL, PB*/JAR, PCP…) se traducen a puestos con la tabla `funciones` de `config/base.yaml`. Por defecto la parrilla muestra solo códigos de empleado; `--con-nombres` añade los nombres.

La parrilla se guarda en `salida/parrilla_AAAA-MM-DD.xlsx`. Los tiempos de servicio, turnos y rotaciones se ajustan en `config/base.yaml`.

## Datos

- `ejemplos/` contiene solo datos **inventados**.
- Los datos operativos reales van en `datos/`, que está excluido de Git. No subas al repositorio vuelos, cuadrantes ni datos personales reales.

## Pendiente

- Confirmar el significado de las funciones PCP, GHA, BH* y PB* y de los colores del cuadrante.
- Rotaciones reales en el modo plantilla: 6x3 = 3 mañanas + 3 tardes + 3 libres; 4x4 = 2 + 2 + 4.
- Comparar grupo a grupo con la parrilla real usando cuadrante y vuelos del mismo periodo.
- Estándares por tipo de avión y compañía, y tiempos de desplazamiento entre puestos.
- Reglas de convenio (descansos, horas anuales, festivos) y planificación mensual y anual.
- Interfaz web para planificadores y RAMPCOs.

## Cuadrante mensual a partir de los vuelos del mes

```bash
planer-mes --mes 2026-11 --vuelos Flights-noviembre.xlsx \
           --referencia cuadrante_octubre.xlsx --mes-referencia 2026-10
```

- Del cuadrante de referencia aprende, para cada persona: función, rotación (6x3, 4x4 o irregular), qué días de su ciclo son de mañana o de tarde y cuántas horas hace al día.
- La rotación continúa en el mes nuevo sin reiniciarse.
- Cada día calcula cuántos equipos hacen falta cada 15 minutos y elige la hora de entrada de cada persona para cubrirlo, con 12 horas de descanso entre jornadas.
- A las personas irregulares solo las llama si hacen falta, sin pasar de los días que hicieron en el mes de referencia.
- Quien hacía turnos partidos puede recibir un partido: sus dos tramos habituales con una pausa de 1 a 5 horas.
- Con `--contratos contratos.xlsx` (columnas EMPLEADO, CONTRATO) aplica las reglas de `contratos` de la configuración: los TC mantienen sus 8 horas, a los de concreción horaria no se les mueve la hora y a los parciales se les recortan las horas que sobran según los vuelos, sin bajar del mínimo `jornada_minima_respecto_referencia`.
- Con `--ausencias listado.xlsx` (columnas EMPLEADO, DESDE, HASTA, MOTIVO) deja fuera a quien está de vacaciones, baja o permiso. Esos días salen con el motivo y el color de la empresa.
- El Excel de salida tiene el formato del cuadrante de la empresa, así que se puede pasar después a `planer --cuadrante`. Incluye las hojas Cobertura, Horas y Curva.

Pendiente: demanda de jardineras e hipódromo. Por ahora esas personas mantienen su horario habitual.

## Web sencilla (en tu ordenador)

En Windows, doble clic en `arrancar_web.bat`.
- La primera vez instala lo necesario. Hace falta tener Python instalado.
- Después se abre el navegador con cuatro pestañas:
  - **Plantilla y ausencias**: apuntas bajas, vacaciones, sanciones y permisos, y das el alta cuando la persona vuelve. Se guardan en `datos/registro/` (fuera de Git). Desde aquí también se reorganiza un cuadrante ya publicado: el programa cambia el horario a las menos personas posibles para cubrir a quien falta y entrega la lista de cambios (hoja Cambios del Excel).
  - **Rotaciones del año**: subes el último cuadrante (y, si quieres, el del mes anterior) y descargas el calendario del año que elijas, con cada día de mañana, de tarde o libre. La rotación continúa desde donde va cada persona; no se reinicia en enero.
  - **Cuadrante del mes**: subes los vuelos del mes, el cuadrante de referencia y, si quieres, las ausencias, y descargas el cuadrante. Las ausencias apuntadas se tienen en cuenta solas.
  - **Parrilla del día**: subes el cuadrante y los vuelos del día, y descargas la parrilla. Quien esté de baja o de vacaciones no entra en ningún equipo.
- Todo se calcula en el propio ordenador y los archivos no se envían a ningún sitio.

En Linux o Mac: `pip install -e .[web]` y después `streamlit run web/app.py`.
