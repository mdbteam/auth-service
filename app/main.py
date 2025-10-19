# app/main.py

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
import pyodbc
from dotenv import load_dotenv

load_dotenv()

from app.models import UserCreate, TokenResponse, UserPublic, UserInDB
from app.database import get_db_connection
from app.auth_utils import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_active_user
)
from app.utils import validar_rut

app = FastAPI(
    title="Servicio de Autenticación - Chambee",
    description="Gestiona el registro, login y tokens de los usuarios.",
    version="1.0.0"
)

# Constantes de Roles y Estados
ROLE_ADMIN, ROLE_CLIENTE, ROLE_PROVEEDOR, ROLE_HYBRID = 0, 1, 2, 3
STATUS_ACTIVO = 'activo'


@app.get("/", tags=["Status"])
def root():
    return {"message": "Auth Service funcionando 🚀"}


@app.post("/auth/register", status_code=200, response_model=UserPublic, tags=["Autenticación y Usuarios"])
def register_client(user_data: UserCreate, conn: pyodbc.Connection = Depends(get_db_connection)):
    if not validar_rut(user_data.rut):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="RUT inválido.")

    cursor = conn.cursor()
    # Buscamos si ya existe un usuario con ese RUT o ese CORREO
    cursor.execute("SELECT id_usuario, id_rol, rut, correo, foto_url FROM Usuarios WHERE rut = ? OR correo = ?",
                   user_data.rut, user_data.correo)
    existing_user = cursor.fetchone()

    if existing_user:
        # --- LÓGICA CORREGIDA Y COMPLETA ---
        # Verificamos si el usuario encontrado tiene el mismo RUT y es un Prestador
        if existing_user.rut == user_data.rut and existing_user.id_rol == ROLE_PROVEEDOR:

            # Adicionalmente, si el correo es diferente, verificamos que el nuevo correo no esté ya en uso por OTRA persona
            if existing_user.correo != user_data.correo:
                cursor.execute("SELECT id_usuario FROM Usuarios WHERE correo = ?", user_data.correo)
                if cursor.fetchone():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail="El nuevo correo electrónico ya está en uso por otro usuario.")

            # Si un Prestador (rol 2) se registra, se convierte en Híbrido (rol 3) y actualizamos sus datos
            try:
                cursor.execute(
                    """
                    UPDATE Usuarios 
                    SET id_rol = ?, nombres = ?, primer_apellido = ?, segundo_apellido = ?, correo = ?, direccion = ?, genero = ?, fecha_nacimiento = ?
                    WHERE id_usuario = ?
                    """,
                    ROLE_HYBRID, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                    user_data.correo, user_data.direccion, user_data.genero, user_data.fecha_nacimiento,
                    existing_user.id_usuario
                )
                conn.commit()
            except pyodbc.Error as e:
                conn.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail=f"Error al actualizar el rol del usuario: {e}")
            finally:
                cursor.close()

            return UserPublic(
                id=str(existing_user.id_usuario),
                nombres=user_data.nombres,
                primer_apellido=user_data.primer_apellido,
                correo=user_data.correo,
                rol="híbrido",
                foto_url=existing_user.foto_url,
                genero=user_data.genero,
                fecha_nacimiento=user_data.fecha_nacimiento
            )
        else:
            # Si el RUT o correo ya existe y no es el caso de un prestador actualizándose, es un conflicto
            cursor.close()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="El RUT o correo ya está registrado por otro usuario.")
    else:
        # --- LÓGICA DE CREACIÓN PARA UN USUARIO COMPLETAMENTE NUEVO ---
        hashed_password = get_password_hash(user_data.password)
        try:
            # La foto_url se inserta por defecto desde la base de datos
            cursor.execute(
                """
                INSERT INTO Usuarios (rut, nombres, primer_apellido, segundo_apellido, correo, contrasena, direccion, id_rol, estado, genero, fecha_nacimiento) 
                OUTPUT INSERTED.id_usuario, INSERTED.foto_url 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                user_data.rut, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                user_data.correo, hashed_password, user_data.direccion, ROLE_CLIENTE, STATUS_ACTIVO,
                user_data.genero, user_data.fecha_nacimiento
            )
            result = cursor.fetchone()
            new_user_id, new_user_foto_url = result[0], result[1]

            cursor.execute("INSERT INTO Perfil (id_usuario) VALUES (?)", new_user_id)
            conn.commit()
        except pyodbc.Error as e:
            conn.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Error en la base de datos: {e}")
        finally:
            cursor.close()

        return UserPublic(
            id=str(new_user_id),
            nombres=user_data.nombres,
            primer_apellido=user_data.primer_apellido,
            correo=user_data.correo,
            rol="cliente",
            foto_url=new_user_foto_url,
            genero=user_data.genero,
            fecha_nacimiento=user_data.fecha_nacimiento
        )


# --- (El resto del archivo, login y /users/me, no necesita cambios) ---
@app.post("/auth/login", response_model=TokenResponse, tags=["Autenticación y Usuarios"])
def login_for_access_token(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    correo_usuario = form_data.username
    password_usuario = form_data.password

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id_usuario, nombres, primer_apellido, contrasena, id_rol, estado, foto_url, genero, fecha_nacimiento
        FROM Usuarios WHERE correo = ?
        """,
        correo_usuario
    )
    user_record = cursor.fetchone()

    if not user_record or not verify_password(password_usuario, user_record.contrasena):
        cursor.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    if user_record.estado != STATUS_ACTIVO:
        cursor.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta no está activa.")

    cursor.close()

    rol_map = {ROLE_CLIENTE: "cliente", ROLE_PROVEEDOR: "prestador", ROLE_HYBRID: "híbrido",
               ROLE_ADMIN: "administrador"}
    rol_str = rol_map.get(user_record.id_rol, "desconocido")

    access_token = create_access_token(data={"sub": str(user_record.id_usuario), "rol": rol_str})

    usuario_publico = UserPublic(
        id=str(user_record.id_usuario),
        nombres=user_record.nombres,
        primer_apellido=user_record.primer_apellido,
        correo=correo_usuario,
        rol=rol_str,
        foto_url=user_record.foto_url,
        genero=user_record.genero,
        fecha_nacimiento=user_record.fecha_nacimiento
    )
    return TokenResponse(token=access_token, usuario=usuario_publico)


@app.get("/users/me", response_model=UserPublic, tags=["Autenticación y Usuarios"])
def read_users_me(current_user: UserInDB = Depends(get_current_active_user)):
    rol_map = {ROLE_CLIENTE: "cliente", ROLE_PROVEEDOR: "prestador", ROLE_HYBRID: "híbrido",
               ROLE_ADMIN: "administrador"}
    rol_str = rol_map.get(current_user.id_rol, "desconocido")

    return UserPublic(
        id=str(current_user.id_usuario),
        nombres=current_user.nombres,
        primer_apellido=current_user.primer_apellido,
        correo=current_user.correo,
        rol=rol_str,
        foto_url=current_user.foto_url,
        genero=current_user.genero,
        fecha_nacimiento=current_user.fecha_nacimiento
    )