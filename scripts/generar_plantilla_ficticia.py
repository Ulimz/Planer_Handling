"""Genera una plantilla ficticia de personal de rampa para una base de handling.

Uso: python scripts/generar_plantilla_ficticia.py [--escala 1.0] [--semilla 42] [--salida plantilla_ficticia.xlsx]
"""
import argparse
import random
from datetime import date, timedelta

import pandas as pd

# Plantilla base de una base mediana (escala 1.0)
PLANTILLA_BASE = {
    "TL": 24,
    "PB/TOW": 24,
    "Carretero": 24,
    "Cintero": 24,
    "Operario": 30,
    "Jardinero": 18,
    "Hipodromo": 24,
}
MANDOS_POR_ROTACION = 2

# Reparto de contratos del personal operativo
CONTRATOS = [
    ("Fijo tiempo completo", 0.60),
    ("Tiempo parcial", 0.20),
    ("Fijo discontinuo", 0.15),
    ("Eventual", 0.05),
]

# TL y PB/TOW son casi siempre fijos a tiempo completo.
CONTRATOS_ESPECIALES = {
    "TL": [("Fijo tiempo completo", 0.9), ("Fijo discontinuo", 0.1)],
    "PB/TOW": [("Fijo tiempo completo", 0.85), ("Fijo discontinuo", 0.15)],
}

# Habilitaciones extra que suele tener cada categoria (probabilidad)
HAB_EXTRA = {
    "TL": {"PB/TOW": 0.5, "Carretero": 0.8, "Cintero": 0.8, "Operario": 1.0},
    "PB/TOW": {"Carretero": 0.7, "Operario": 1.0},
    "Carretero": {"Cintero": 0.5, "Operario": 1.0},
    "Cintero": {"Carretero": 0.6, "Operario": 1.0},
    "Operario": {"Carretero": 0.3, "Cintero": 0.3},
    "Jardinero": {"Carretero": 0.2},
    "Hipodromo": {"Operario": 0.6, "Carretero": 0.3},
}

HOY = date(2026, 10, 26)


def fecha_aleatoria(desde, hasta):
    if hasta <= desde:
        return desde
    return desde + timedelta(days=random.randint(0, (hasta - desde).days))


def elegir_contrato(categoria):
    r, acum = random.random(), 0.0
    for nombre, p in CONTRATOS_ESPECIALES.get(categoria, CONTRATOS):
        acum += p
        if r < acum:
            return nombre
    return "Fijo tiempo completo"


def generar(escala):
    empleados, habilitaciones = [], []
    n = 0

    def nuevo_id():
        nonlocal n
        n += 1
        return f"E{n:04d}"

    def anadir_hab(emp_id, hab, alta):
        obtenida = fecha_aleatoria(alta, HOY)
        habilitaciones.append({
            "id_empleado": emp_id,
            "habilitacion": hab,
            "fecha_obtencion": obtenida,
            # Reciclaje cada 2 o 3 anos; algunas caducan pronto a proposito
            "fecha_caducidad": fecha_aleatoria(HOY - timedelta(days=30), HOY + timedelta(days=3 * 365)),
        })

    rotacion_6x3 = 0
    for categoria, cantidad in PLANTILLA_BASE.items():
        for _ in range(round(cantidad * escala)):
            emp_id = nuevo_id()
            contrato = elegir_contrato(categoria)
            alta = fecha_aleatoria(date(2005, 1, 1), HOY - timedelta(days=60))
            fila = {
                "id_empleado": emp_id,
                "categoria_principal": categoria,
                "contrato": contrato,
                "rotacion": "",
                "horas_turno": "",
                "horas_semanales": "",
                "llamamiento_inicio": "",
                "llamamiento_fin": "",
                "fecha_alta": alta,
            }
            if contrato == "Fijo tiempo completo":
                fila["rotacion"] = "6x3-" + "ABC"[rotacion_6x3 % 3]
                rotacion_6x3 += 1
                fila["horas_turno"] = 8
            elif contrato == "Tiempo parcial":
                fila["horas_turno"] = random.choice([4, 5, 6])
                fila["horas_semanales"] = random.choice([20, 24, 25, 30])
            elif contrato == "Fijo discontinuo":
                fila["horas_turno"] = 8
                fila["llamamiento_inicio"] = date(2027, random.choice([3, 4, 5]), 1)
                fila["llamamiento_fin"] = date(2027, random.choice([10, 11]), 1) - timedelta(days=1)
            else:  # Eventual
                fila["fecha_alta"] = date(2027, 6, 1)
                fila["horas_turno"] = 8
                fila["llamamiento_inicio"] = date(2027, 6, 1)
                fila["llamamiento_fin"] = date(2027, 9, 30)
            empleados.append(fila)

            anadir_hab(emp_id, categoria, fila["fecha_alta"])
            for extra, p in HAB_EXTRA.get(categoria, {}).items():
                if random.random() < p:
                    anadir_hab(emp_id, extra, fila["fecha_alta"])

    for grupo in range(1, 5):
        for _ in range(max(1, round(MANDOS_POR_ROTACION * escala))):
            emp_id = nuevo_id()
            alta = fecha_aleatoria(date(2005, 1, 1), date(2020, 1, 1))
            empleados.append({
                "id_empleado": emp_id,
                "categoria_principal": "Mando intermedio",
                "contrato": "Fijo tiempo completo",
                "rotacion": f"4x4-{grupo}",
                "horas_turno": 10,
                "horas_semanales": "",
                "llamamiento_inicio": "",
                "llamamiento_fin": "",
                "fecha_alta": alta,
            })
            for hab in ["Mando intermedio", "TL", "PB/TOW", "Carretero", "Cintero", "Operario"]:
                anadir_hab(emp_id, hab, alta)

    return pd.DataFrame(empleados), pd.DataFrame(habilitaciones)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--escala", type=float, default=1.0, help="1.0 = base mediana, 3.0 = base grande")
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--salida", default="ejemplos/plantilla_ficticia.xlsx")
    args = parser.parse_args()

    random.seed(args.semilla)
    plantilla, habs = generar(args.escala)
    resumen = pd.crosstab(plantilla["categoria_principal"], plantilla["contrato"], margins=True, margins_name="Total")

    with pd.ExcelWriter(args.salida) as writer:
        plantilla.to_excel(writer, sheet_name="Plantilla", index=False)
        habs.to_excel(writer, sheet_name="Habilitaciones", index=False)
        resumen.to_excel(writer, sheet_name="Resumen")
    print(f"{len(plantilla)} empleados y {len(habs)} habilitaciones en {args.salida}")
    print(resumen.to_string())


if __name__ == "__main__":
    main()
