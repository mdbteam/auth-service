#app/auth_utils.py

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
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --- DEPENDENCIA DE AUTENTICACIÓN ---

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
        token_iat: int = payload.get("iat")
        if user_id is None or token_iat is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    cursor = conn.cursor()
    # Obtenemos todos los campos de la tabla Usuarios
    cursor.execute(
        """
        SELECT 
            id_usuario, nombres, primer_apellido, rut, correo, contrasena, 
            id_rol, estado, foto_url, genero, fecha_nacimiento
        FROM Usuarios WHERE id_usuario = ?
        """,
        int(user_id)
    )
    user_record = cursor.fetchone()
    cursor.close()

    if user_record is None:
        raise credentials_exception

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
    )

    if user_in_db.estado != 'activo':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo o baneado")

    return user_in_db