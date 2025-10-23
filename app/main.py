# app/main.py

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
import pyodbc
from dotenv import load_dotenv

load_dotenv(override=True)  # Cargar .env primero y forzar sobrescritura

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
    cursor.execute("SELECT id_usuario, id_rol, rut, correo, foto_url FROM Usuarios WHERE rut = ? OR correo = ?",
                   user_data.rut, user_data.correo)
    existing_user = cursor.fetchone()

    if existing_user:
        if existing_user.rut == user_data.rut and existing_user.id_rol == ROLE_PROVEEDOR:
            if existing_user.correo != user_data.correo:
                cursor.execute("SELECT id_usuario FROM Usuarios WHERE correo = ?", user_data.correo)
                if cursor.fetchone():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail="El nuevo correo electrónico ya está en uso por otro usuario.")
            try:
                cursor.execute(
                    """
                    UPDATE Usuarios 
                    SET id_rol = ?, nombres = ?, primer_apellido = ?, segundo_apellido = ?, correo = ?, direccion = ?, genero = ?, fecha_nacimiento = ?, token_valido_desde = GETDATE()
                    WHERE id_usuario = ?
                    """,
                    ROLE_HYBRID, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                    user_data.correo, user_data.direccion, user_data.genero, user_data.fecha_nacimiento,
                    existing_user.id_usuario
                )
                conn.commit()
            except pyodbc.Error as e:
                conn.rollback();
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail=f"Error al actualizar rol: {e}")
            finally:
                cursor.close()
            return UserPublic(id=str(existing_user.id_usuario), nombres=user_data.nombres,
                              primer_apellido=user_data.primer_apellido, correo=user_data.correo, rol="híbrido",
                              foto_url=existing_user.foto_url, genero=user_data.genero,
                              fecha_nacimiento=user_data.fecha_nacimiento)
        else:
            cursor.close();
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="El RUT o correo ya está registrado por otro usuario.")
    else:
        hashed_password = get_password_hash(user_data.password)
        try:
            cursor.execute(
                """
                INSERT INTO Usuarios (rut, nombres, primer_apellido, segundo_apellido, correo, contrasena, direccion, id_rol, estado, genero, fecha_nacimiento, token_valido_desde) 
                OUTPUT INSERTED.id_usuario, INSERTED.foto_url 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                """,
                user_data.rut, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                user_data.correo, hashed_password, user_data.direccion, ROLE_CLIENTE, STATUS_ACTIVO,
                user_data.genero, user_data.fecha_nacimiento
            )
            result = cursor.fetchone()
            new_user_id, new_user_foto_url = result[0], result[1]
            cursor.execute("INSERT INTO Perfil (id_usuario) VALUES (?)", new_user_id)  # Creamos perfil vacío
            conn.commit()
        except pyodbc.Error as e:
            conn.rollback();
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en BBDD: {e}")
        finally:
            cursor.close()

        # Importante: El status code para creación es 201
        from fastapi import Response
        response = Response(status_code=status.HTTP_201_CREATED)

        return UserPublic(id=str(new_user_id), nombres=user_data.nombres, primer_apellido=user_data.primer_apellido,
                          correo=user_data.correo, rol="cliente", foto_url=new_user_foto_url, genero=user_data.genero,
                          fecha_nacimiento=user_data.fecha_nacimiento)


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

    # 1. Verificar contraseña y estado
    if not user_record or not verify_password(password_usuario, user_record.contrasena):
        cursor.close()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    if user_record.estado != STATUS_ACTIVO:
        cursor.close()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta no está activa.")


    try:
        cursor.execute("UPDATE Usuarios SET token_valido_desde = GETDATE() WHERE id_usuario = ?",
                       user_record.id_usuario)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback()
        cursor.close()  # Cerramos el cursor si hay error aquí
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"No se pudo actualizar la sesión: {e}")

    # Cerramos el cursor después de usarlo
    cursor.close()

    # 3. Creamos el nuevo token DESPUÉS de actualizar la BBDD
    rol_map = {ROLE_CLIENTE: "cliente", ROLE_PROVEEDOR: "prestador", ROLE_HYBRID: "híbrido",
               ROLE_ADMIN: "administrador"}
    rol_str = rol_map.get(user_record.id_rol, "desconocido")
    access_token = create_access_token(data={"sub": str(user_record.id_usuario), "rol": rol_str})

    # 4. Devolvemos la respuesta
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
        foto_url=current_user.foto_url,  # Asegúrate que UserInDB traiga esto
        genero=current_user.genero,  # Asegúrate que UserInDB traiga esto
        fecha_nacimiento=current_user.fecha_nacimiento  # Asegúrate que UserInDB traiga esto
    )