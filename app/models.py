
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


config = ConfigDict(
    populate_by_name=True,
    from_attributes=True
)

class User(BaseModel):
    rut: str = Field(..., max_length=12)
    nombres: str = Field(..., max_length=100)
    primer_apellido: str = Field(..., max_length=100)
    segundo_apellido: Optional[str] = Field(None, max_length=100)
    correo: str = Field(..., max_length=100, alias="email")
    password: str = Field(..., min_length=8)
    direccion: Optional[str] = Field(None, max_length=255)
    rol: str = Field(default="user", max_length=50)
    estado: str = Field(default="activo", max_length=50)

    model_config = config

class CertificacionCreate(BaseModel):
    id_usuario: int
    nombre_certificacion: str = Field(..., min_length=5, max_length=255)
    model_config = config


class CertificacionResponse(BaseModel):
    id_certificacion: int
    id_usuario: int
    nombre_certificacion: str
    fecha_creacion: str

    model_config = config
