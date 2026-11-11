"""Contraseñas y sesiones. Solo librería estándar: scrypt para las contraseñas y tokens al azar
para las sesiones (en la base de datos solo se guarda su huella)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

LARGO_MINIMO = 10
N, R, P = 2 ** 14, 8, 1


def hash_contrasena(contrasena: str) -> str:
    sal = secrets.token_bytes(16)
    clave = hashlib.scrypt(contrasena.encode(), salt=sal, n=N, r=R, p=P, dklen=32)
    return f"scrypt${N}${R}${P}${base64.b64encode(sal).decode()}${base64.b64encode(clave).decode()}"


def comprobar_contrasena(contrasena: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, clave = guardado.split("$")
        calculada = hashlib.scrypt(contrasena.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
                                   dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada, base64.b64decode(clave))


def problema_contrasena(contrasena: str, usuario: str = "") -> str | None:
    """Por qué no vale una contraseña nueva, o None si vale."""
    if len(contrasena) < LARGO_MINIMO:
        return f"La contraseña tiene que tener al menos {LARGO_MINIMO} caracteres."
    if usuario and usuario.lower() in contrasena.lower():
        return "La contraseña no puede llevar el nombre de usuario."
    if contrasena.isdigit() or contrasena.isalpha():
        return "La contraseña tiene que mezclar letras y números o signos."
    return None


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
