# AEROS en un servidor central (fase 1)

La misma web, pero en un servidor: cada usuario entra con su cuenta y solo ve sus bases y las
herramientas que tiene permitidas. Sin `AEROS_SERVIDOR` la web sigue funcionando como siempre, en el
ordenador, sin cuentas.

## Quién ve qué

| Quién | Qué hace |
| --- | --- |
| Administrador de AEROS | Da de alta empresas y bases, activa las herramientas contratadas de cada base, bloquea una empresa o una base y crea la primera cuenta de la central. No ve cuadrantes ni personal. |
| Central de la empresa | Ve y cambia todo en todas las bases de su empresa, cambia las reglas de la empresa, crea usuarios y les da bases. Ve el registro de su empresa. |
| Jefe de base | Todo en las bases que le den, salvo reglas y usuarios. |
| Planificador / RAMPCO | Igual que el jefe de base (de momento no hay paso de «publicar»). |
| Consulta | Solo ver: los botones que guardan algo salen desactivados. |

A cada usuario se le puede limitar a algunas herramientas de una base (por ejemplo, solo parrilla).
Herramientas: datos, cuadrante (y resumen), parrilla, pasaje, ausencias, rotaciones, vacaciones y
personal. Una empresa nunca ve nada de otra: lo comprueba cada operación (tests/test_servidor.py).

## Datos y protección de datos

- Personal solo con códigos (P0001…), los de AEROS: los nombres se cambian por código al subir el
  archivo y no se guardan. La huella que asigna siempre el mismo código a la misma persona se guarda
  por empresa, con una sal propia.
- Cuentas, permisos, fichas de personal y registro en la base de datos (`AEROS_BD`). Cuadrantes,
  vuelos y ausencias de cada base en su carpeta: `AEROS_DATOS/<empresa>/bases/<base>/`.
- Contraseñas con scrypt (10 caracteres o más, letras y números). Cinco fallos bloquean la cuenta 15
  minutos. Las sesiones caducan a las 10 horas. Cambiar la contraseña o desactivar a alguien cierra
  sus sesiones.
- Registro de entradas, permisos, datos subidos, cuadrantes generados o corregidos y ausencias.

## Ponerlo en marcha

```
pip install -e .[servidor]
export AEROS_BD=postgresql+psycopg://aeros:CLAVE@localhost/aeros   # o sin ponerla: SQLite en AEROS_DATOS
export AEROS_DATOS=/srv/aeros/datos
aeros-servidor iniciar
aeros-servidor crear-admin admin.aeros
AEROS_SERVIDOR=1 streamlit run web/app.py --server.headless true
```

Delante, un proxy con HTTPS (Caddy o Nginx). El servidor, sus copias y la base de datos en la UE.

### Base piloto con datos ficticios

```
python scripts/porcentajes_plantilla.py --cuadrante REAL.xlsx --anio 2026 --mes 11 \
    --contratos CONTRATOS.xlsx --formacion FORMACION.xlsx --salida porcentajes.yaml
python scripts/plantilla_ficticia.py --porcentajes porcentajes.yaml --desde 2026-10 --hasta 2026-11 --salida piloto/
aeros-servidor piloto piloto/
```

El primero solo saca totales y proporciones de la plantilla real (cuántos de cada función, qué parte
tiene cada contrato, rotación, capacitación, turnos y horas del mes), sin nombres ni códigos. Aun así
describe una empresa real: no se sube al repositorio. El segundo crea personas que no existen con
esas proporciones y comprueba, leyendo lo generado con los mismos lectores de AEROS, que los
porcentajes coinciden. `piloto` crea la empresa «piloto» con la base PIL, las cuentas de cada rol
(enseña sus contraseñas una vez) y carga los datos.

## Falta (siguientes fases)

- Paso de borrador a publicado en el cuadrante y aviso a la central.
- Generar el cuadrante en segundo plano (hoy la pantalla espera mientras calcula).
- Segundo factor para administrador y central.
- Varias empresas a la vez con reglas propias desde el primer día (ya se puede, falta probarlo con una
  empresa real) y el contrato de encargado del tratamiento (art. 28 RGPD) con cada una.
- Pantallas nuevas pensadas para móvil (la web de hoy es la de siempre con cuentas).
