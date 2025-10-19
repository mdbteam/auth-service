# app/models.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

# --- MODELOS DE AUTENTICACIÓN Y USUARIO ---

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

class UserPublic(BaseModel):
    """Modelo de respuesta pública con todos los datos del usuario."""
    id: str
    nombres: str
    primer_apellido: str
    correo: str
    rol: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None

class UserInDB(BaseModel):
    id_usuario: int
    nombres: str
    primer_apellido: str
    rut: str
    correo: str
    hashed_password: str
    id_rol: int
    estado: str
    foto_url: str
    genero: Optional[str] = None
    fecha_nacimiento: Optional[date] = None

class Login(BaseModel):
    correo: str = Field(..., max_length=100)
    password: str = Field(..., min_length=8)

class TokenResponse(BaseModel):
    """Modelo de respuesta para el login con todos los datos."""
    token: str
    usuario: UserPublic