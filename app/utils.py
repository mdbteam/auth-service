from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hashea la contraseña con bcrypt"""
    return pwd_context.hash(password)

def validar_rut(rut: str) -> bool:
    rut = rut.replace(".", "").replace("-", "").upper()

    if not rut[:-1].isdigit():
        return False

    cuerpo = rut[:-1]
    dv = rut[-1]

    suma = 0
    multiplo = 2
    for d in reversed(cuerpo):
        suma += int(d) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1

    resto = 11 - (suma % 11)
    dv_esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)

    return dv == dv_esperado
