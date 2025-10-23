# app/auth_utils.py

import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
import pyodbc

from app.database import get_db_connection
from app.models import UserInDB

# --- CONFIGURACIÓN DE SEGURIDAD ---

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está configurada en las variables de entorno.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# --- FUNCIONES DE HASHING ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# --- FUNCIONES DE TOKEN JWT ---

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Añadimos la fecha de emisión ('issued at')
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --- DEPENDENCIA DE AUTENTICACIÓN (CORREGIDA) ---

def get_current_active_user(
    token: str = Depends(oauth2_scheme),
    conn: pyodbc.Connection = Depends(get_db_connection)
) -> UserInDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        token_iat: int = payload.get("iat") # Obtenemos 'issued at' del token
        if user_id is None or token_iat is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    cursor = conn.cursor()
    # --- OBTENEMOS token_valido_desde DE LA BBDD ---
    cursor.execute(
        """
        SELECT
            id_usuario, nombres, primer_apellido, rut, correo, contrasena,
            id_rol, estado, foto_url, genero, fecha_nacimiento, token_valido_desde
        FROM Usuarios WHERE id_usuario = ?
        """,
        int(user_id)
    )
    user_record = cursor.fetchone()
    cursor.close()

    if user_record is None:
        raise credentials_exception

    # --- AÑADIMOS COMPARACIÓN DE FECHAS ---
    # Convertimos el 'iat' del token a datetime con UTC
    token_fecha_creacion = datetime.fromtimestamp(token_iat, tz=timezone.utc)
    # Hacemos la fecha de la BBDD consciente del timezone UTC (si no es None)
    db_fecha_valida = None
    if user_record.token_valido_desde:
        # Asumiendo que SQL Server guarda DATETIME2 sin zona horaria específica,
        # lo tratamos como UTC para comparar con el token 'iat' que sí tiene zona UTC.
        db_fecha_valida = user_record.token_valido_desde.replace(tzinfo=timezone.utc)

    # Si hay una fecha válida en BBDD y el token fue creado ANTES, es inválido
    if db_fecha_valida and token_fecha_creacion < db_fecha_valida:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ha expirado (inicio de sesión detectado en otro dispositivo)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # --- FIN COMPARACIÓN ---

    # Creamos el objeto UserInDB (asegúrate que el modelo tenga todos los campos)
    user_in_db = UserInDB(
        id_usuario=user_record.id_usuario,
        nombres=user_record.nombres,
        primer_apellido=user_record.primer_apellido,
        rut=user_record.rut,
        correo=user_record.correo,
        hashed_password=user_record.contrasena,
        id_rol=user_record.id_rol,
        estado=user_record.estado,
        foto_url=user_record.foto_url,
        genero=user_record.genero,
        fecha_nacimiento=user_record.fecha_nacimiento
        # No incluimos token_valido_desde en el modelo UserInDB
    )

    if user_in_db.estado != 'activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo o baneado")

    return user_in_db