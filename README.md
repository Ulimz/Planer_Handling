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

La parrilla se guarda en `salida/parrilla_AAAA-MM-DD.xlsx`. Los tiempos de servicio, turnos y rotaciones se ajustan en `config/base.yaml`.

## Datos

- `ejemplos/` contiene solo datos **inventados**.
- Los datos operativos reales van en `datos/`, que está excluido de Git. No subas al repositorio vuelos, cuadrantes ni datos personales reales.

## Pendiente

- Leer el cuadrante mensual y la hoja de grupos con el formato de PARRITRON y comparar con la parrilla real.
- Estándares por tipo de avión y compañía, y tiempos de desplazamiento entre puestos.
- Reglas de convenio (descansos, horas anuales, festivos) y planificación mensual y anual.
- Interfaz web para planificadores y RAMPCOs.
