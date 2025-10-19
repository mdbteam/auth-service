# app/utils.py

def validar_rut(rut: str) -> bool:
    """
    Valida un RUT chileno con su dígito verificador.
    """
    rut = rut.replace(".", "").replace("-", "").upper()
    if not rut[:-1].isdigit() or len(rut) < 8: return False
    cuerpo, dv = rut[:-1], rut[-1]

    suma = 0
    multiplo = 2
    for d in reversed(cuerpo):
        suma += int(d) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1

    resto = 11 - (suma % 11)
    dv_esperado = "0" if resto == 11 else "K" if resto == 10 else str(resto)

    return dv == dv_esperado