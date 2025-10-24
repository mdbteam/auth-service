# auth-service/app/models.py
from pydantic import BaseModel, Field # Import Field
from typing import Optional
from datetime import date, datetime # Import datetime

class UserCreate(BaseModel):
    rut: str = Field(..., max_length=12)
    nombres: str = Field(..., max_length=100)
    primer_apellido: str = Field(..., max_length=100)
    segundo_apellido: Optional[str] = Field(None, max_length=100)
    correo: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8)
    direccion: Optional[str] = Field(None, max_length=255)
    genero: Optional[str] = Field(None, max_length=50)
    fecha_nacimiento: Optional[date] = None

class UserPublic(BaseModel): # Modelo unificado y COMPLETO
    id: str
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    rut: str
    correo: str
    direccion: Optional[str] = None
    rol: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None

class UserInDB(BaseModel): # Modelo interno completo
    id_usuario: int
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str] = None
    rut: str
    correo: str
    direccion: Optional[str] = None
    # Tell Pydantic that 'hashed_password' corresponds to the 'contrasena' column
    hashed_password: str = Field(alias='contrasena')
    id_rol: int
    estado: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    token_valido_desde: Optional[datetime] = None # Necesario para auth_utils

class TokenResponse(BaseModel):
    token: str
    usuario: UserPublic # Usamos el modelo unificado completo