from pydantic import BaseModel, EmailStr, Field

class User(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=50)
    apellido: str = Field(..., min_length=2, max_length=50)
    rut: str
    email: EmailStr
    password: str
