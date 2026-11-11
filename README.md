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

## Cada empresa con su forma de trabajar (`operativa`)

No todas las empresas trabajan como Azul con Ryanair (un equipo completo que hace el vuelo entero). Un perfil puede describir en la sección `operativa` qué **recursos** tiene y qué **tareas** le pide cada vuelo a cada uno: grupos con capataz, PB sueltos que solo sacan salidas, coordinadores de vuelos que siguen varios giros a la vez, jardineras… Con eso se forman la parrilla del día (una hoja por recurso) y la demanda del cuadrante del mes (personas de cada categoría cada 15 minutos).

- `puestos`: quién va en el recurso (si un puesto se repite, la parrilla los numera: Operario 1, Operario 2…).
- `tareas`: `giro`, `solo_salida`, `solo_llegada` (el recurso hace el vuelo) o `salida`, `llegada` (una tarea en cada salida o llegada, como el PB o la jardinera), con los minutos antes y después del STA/STD.
- `simultaneos` y `max_vuelos_dia`: vuelos a la vez y vuelos al día que lleva un mismo recurso (un coordinador).
- `puede_hacer_de`: quién cubre otra categoría si le sobra tiempo; `coste_falta`: cuánto pesa cada hueco.
- `categorias`, `solo_remoto`, `en_cuadrante`, `principal`, `hoja`, `codigo`: ver `src/planer_handling/operativa.py`.

El ejemplo completo está en `config/ejemplo_grupos_capataz.yaml` (grupos de capataz + TRT + 3 operarios, PB aparte 10 minutos antes del STD y coordinador de vuelos; cifras orientativas). Un perfil sin `operativa`, como `base.yaml`, funciona exactamente igual que antes.

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
- Después se abre el navegador con siete pestañas:
  - **Resumen**: subes un cuadrante y los vuelos del mes y ves, cada 15 minutos, cuánta gente hay frente a la que piden los vuelos. Si subes otro cuadrante del mismo mes (por ejemplo el hecho a mano), compara horas y huecos.
  - **Plantilla y ausencias**: apuntas bajas, vacaciones, sanciones y permisos, y das el alta cuando la persona vuelve. Se guardan en `datos/registro/` (fuera de Git). Desde aquí también se reorganiza un cuadrante ya publicado: el programa cambia el horario a las menos personas posibles para cubrir a quien falta y entrega la lista de cambios (hoja Cambios del Excel).
  - **Rotaciones del año**: subes el último cuadrante (y, si quieres, el del mes anterior) y descargas el calendario del año que elijas, con cada día de mañana, de tarde o libre. La rotación continúa desde donde va cada persona; no se reinicia en enero.
  - **Vacaciones del año**: subes las solicitudes (Empleado, Función, Puntos, Antigüedad y las quincenas por orden de preferencia) y el programa reparte las vacaciones del año siguiente por puntos: elige primero quien menos puntos lleva, cada quincena suma los puntos de su temporada y en cada quincena solo puede estar fuera un cupo de cada función. Temporadas, puntos y cupos están en `vacaciones` de la configuración. El reparto se puede apuntar de golpe como ausencias.
  - **Cuadrante del mes**: subes los vuelos del mes, el cuadrante de referencia y, si quieres, las ausencias, y descargas el cuadrante. Las ausencias apuntadas se tienen en cuenta solas.
  - **Parrilla del día**: subes el cuadrante y los vuelos del día, y descargas la parrilla. Quien esté de baja o de vacaciones no entra en ningún equipo. Si la configuración tiene `pasaje` activo, la parrilla trae también la hoja Pasaje: facturación y puertas de embarque de cada vuelo, oficina, lost and found y los responsables de pasaje.
  - **Empresa y reglas**: el perfil de la empresa sin tocar archivos: turnos y rotaciones, contratos y preavisos del convenio, ventanas de servicio de rampa, pasaje, vacaciones por puntos y funciones. Los perfiles de ejemplo (`config/`) no se sobrescriben: se guardan como empresa nueva en `datos/empresas/` (fuera de Git), solo con lo que cambia. La empresa con la que se planifica se elige en la barra lateral, y un perfil se puede descargar y cargar en otro ordenador.
- Todo se calcula en el propio ordenador y los archivos no se envían a ningún sitio.
- **Pasaje de Azul en Alicante** (`config/azul_alc_pasaje.yaml`): el pasaje con las reglas sacadas de la planificación real de 2026 (Manhattan Live y parrillas de puerta). Check-in de 3 h a 41 min antes del STD en mostradores compartidos (3 agentes más 1 por cada 4,5 vuelos abiertos), 2 agentes por puerta desde 50 min antes (60 en la primera ola), 6 agentes de reserva mientras hay operación, y puestos fijos con su propia categoría: 2 OPS, 1 ticket desk y 1 lost and found, más 3 responsables (DSM y PSM). En `pasaje`, `facturacion.compartida`, `embarque.primera_ola`, `embarque.reserva` y los puestos fijos con `{personas, categoria}` sirven para cualquier empresa.
- **Demo**: el interruptor "Demo con una empresa ficticia" de la barra lateral carga una empresa inventada (`ejemplos/demo/`, se rehace con `python ejemplos/generar_demo.py`): 260 personas (rampa y pasaje), contratos, cuadrante de octubre, vuelos de noviembre con la forma de una operación vacacional desde Reino Unido, y el noviembre que sale del programa y uno "a mano" para compararlos, y las solicitudes de vacaciones de 2027. Usa `config/demo.yaml`, que hereda de `base.yaml` y activa pasaje. Las ausencias de la demo se guardan aparte, en `datos/registro_demo/`.

En Linux o Mac: `pip install -e .[web]` y después `streamlit run web/app.py`.

## En un servidor central, con cuentas y permisos por base

Con `AEROS_SERVIDOR=1` la misma web pide usuario y contraseña, y cada uno ve solo sus bases y
herramientas: el administrador de AEROS da de alta empresas y bases, la central de cada empresa da
los permisos y hay una pestaña Personal para filtrar por base, función, capacitación, contrato y
rotación. Cómo montarlo y la base piloto con datos ficticios: [docs/servidor.md](docs/servidor.md).
