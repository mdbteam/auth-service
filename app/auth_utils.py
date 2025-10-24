# app/auth_utils.py

import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
import pyodbc

from app.database import get_db_connection
from app.models import UserInDB # Asegúrate que UserInDB esté completo en models.py
from datetime import date # Import date

# --- CONFIGURACIÓN DE SEGURIDAD ---

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está configurada en las variables de entorno.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login") # Apunta al endpoint de login


# --- FUNCIONES DE HASHING ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña plana contra su hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Genera el hash de una contraseña."""
    return pwd_context.hash(password)


# --- FUNCIONES DE TOKEN JWT ---

def create_access_token(data: dict):
    """Crea un nuevo token de acceso JWT, incluyendo la fecha de emisión (iat)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Añadimos la fecha de emisión ('issued at') en UTC
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --- DEPENDENCIA DE AUTENTICACIÓN (CON TOLERANCIA) ---

def get_current_active_user(
    token: str = Depends(oauth2_scheme),
    conn: pyodbc.Connection = Depends(get_db_connection)
) -> UserInDB:
    """
    Valida el token JWT, verifica que no sea de una sesión antigua (con tolerancia),
    y devuelve los datos del usuario activo.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        token_iat_timestamp: int = payload.get("iat") # Obtenemos 'issued at' como timestamp
        if user_id is None or token_iat_timestamp is None:
            raise credentials_exception
        # Convertimos el timestamp 'iat' a un objeto datetime con zona horaria UTC
        token_fecha_creacion = datetime.fromtimestamp(token_iat_timestamp, tz=timezone.utc)

    except JWTError:
        raise credentials_exception

    cursor = conn.cursor()
    # Traemos todos los campos necesarios, incluyendo token_valido_desde
    cursor.execute(
        """
        SELECT
            id_usuario, nombres, primer_apellido, segundo_apellido, rut, correo,
            contrasena, direccion, id_rol, estado, foto_url, genero,
            fecha_nacimiento, token_valido_desde
        FROM Usuarios WHERE id_usuario = ?
        """,
        int(user_id)
    )
    user_record = cursor.fetchone()
    cursor.close()

    if user_record is None:
        raise credentials_exception

    # --- COMPARACIÓN DE FECHAS CON TOLERANCIA ---
    db_fecha_valida = None
    if user_record.token_valido_desde:
        # Asumimos que DATETIME2 se guarda sin zona, lo tratamos como UTC
        db_fecha_valida = user_record.token_valido_desde.replace(tzinfo=timezone.utc)

        # Si hay fecha válida Y la diferencia entre el último login y la creación del token
        # es MAYOR a 2 segundos (es decir, el token es significativamente más viejo), lo invalidamos.
        if (db_fecha_valida - token_fecha_creacion) > timedelta(seconds=2):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="La sesión ha expirado (inicio de sesión detectado en otro dispositivo)",
                headers={"WWW-Authenticate": "Bearer"},
            )
    # --- FIN COMPARACIÓN ---

    # Mapeamos a UserInDB (asegúrate que el modelo tenga todos estos campos)
    user_data = dict(zip([column[0] for column in user_record.cursor_description], user_record))
    # Pyodbc puede devolver None para segundo_apellido y direccion, Pydantic lo maneja
    user_in_db = UserInDB(**user_data)


    # Verificamos si el usuario está activo (después de validar el token)
    if user_in_db.estado != 'activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo o baneado")

    return user_in_db