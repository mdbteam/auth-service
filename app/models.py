# app/models.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from fastapi import Form, UploadFile

config = ConfigDict(
    populate_by_name=True,
    from_attributes=True
)


# --- MODELOS DE AUTENTICACIÓN Y USUARIO ---

class User(BaseModel):
    rut: str = Field(..., max_length=12)
    nombres: str = Field(..., max_length=100)
    primer_apellido: str = Field(..., max_length=100)
    segundo_apellido: Optional[str] = Field(None, max_length=100)
    correo: str = Field(..., max_length=100, alias="email")
    password: str = Field(..., min_length=8)
    direccion: Optional[str] = Field(None, max_length=255)
    model_config = config


class Login(BaseModel):
    correo: str = Field(..., max_length=100, alias="email")
    password: str = Field(..., min_length=8)
    model_config = config


class TokenResponse(BaseModel):
    token: str
    usuario: dict


# --- MODELOS DE PRESTADORES (RESPUESTAS) ---

class PrestadorResumen(BaseModel):
    id: str
    nombres: str
    primer_apellido: str
    fotoUrl: str
    # CORREGIDO: Debe ser List[str] para coincidir con el SQL STRING_AGG
    oficios: List[str]
    resumen: str  # Mapea a Perfil.descripcion
    puntuacion: float
    model_config = config


class Servicio(BaseModel):
    id: str
    nombre: str
    precioEstimado: str
    model_config = config


class Resena(BaseModel):
    id: str
    autor: str
    puntuacion: int
    comentario: str
    model_config = config


class Rating(BaseModel):
    stars: int
    count: int
    model_config = config


class PrestadorDetalle(BaseModel):
    id: str
    nombres: str
    primer_apellido: str
    segundo_apellido: Optional[str]
    fotoUrl: str
    # CORREGIDO: Debe ser List[str]
    oficios: List[str]
    # CORREGIDO: Nombre claro para mapear a Perfil.biografia
    biografia_personal: str
    # NUEVO: Para mapear a Perfil.descripcion
    descripcion_trabajo: str
    estaVerificado: bool
    puntuacion: float
    totalReseñas: int
    servicios: List[Servicio]
    reseñas: List[Resena]
    ratingDistribution: List[Rating]
    # NUEVO: Para traer los links de Portafolio
    portafolio_links: List[str]
    model_config = config


# --- MODELO PARA POSTULACIÓN (ENTRADA multipart/form-data) ---
# Este es un modelo de dependencia para manejar los campos de texto
class PostulacionForm:
    # Captura los campos de texto del formulario multipart/form-data
    def __init__(
            self,
            # OBLIGATORIO: Se usa '...'
            oficio: str = Form(..., alias="oficio"),
            # OBLIGATORIO: Se usa '...'
            biografia: str = Form(..., alias="bio"),
            # OPCIONAL: Se usa "" (string vacío) como valor por defecto para evitar el TypeError
            descripcion_trabajo: str = Form("", alias="descripcion_trabajo"),
    ):
        self.oficios_str = oficio
        self.biografia = biografia
        self.descripcion_trabajo = descripcion_trabajo


# --- MODELOS DE CERTIFICACIONES ---

class CertificacionCreate(BaseModel):
    id_usuario: int
    nombre_certificacion: str = Field(..., min_length=5, max_length=255)
    model_config = config


class CertificacionResponse(BaseModel):
    id_certificacion: int
    id_usuario: int
    nombre_certificacion: str
    fecha_creacion: str
    # url_documento: Optional[str] = None
    model_config = config