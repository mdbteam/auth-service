# auth-service/app/main.py
from fastapi import FastAPI, HTTPException, status, Depends, Response # Importar Response
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
import pyodbc
from dotenv import load_dotenv

load_dotenv(override=True) # Cargar .env primero y forzar sobrescritura

# Asegúrate que UserPublic esté importado y completo
from app.models import UserCreate, TokenResponse, UserPublic, UserInDB
from app.database import get_db_connection
from app.auth_utils import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_active_user # Importamos la versión completa
)
from app.utils import validar_rut

app = FastAPI(title="Servicio de Autenticación - Chambee", version="1.0.0")

ROLE_ADMIN, ROLE_CLIENTE, ROLE_PROVEEDOR, ROLE_HYBRID = 0, 1, 2, 3
STATUS_ACTIVO = 'activo'

@app.get("/", tags=["Status"])
def root(): return {"message": "Auth Service funcionando 🚀"}

@app.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=UserPublic, tags=["Autenticación y Usuarios"])
def register_client(user_data: UserCreate, conn: pyodbc.Connection = Depends(get_db_connection)):
    if not validar_rut(user_data.rut):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="RUT inválido.")

    cursor = conn.cursor()
    cursor.execute("SELECT id_usuario, id_rol, rut, correo, foto_url FROM Usuarios WHERE rut = ? OR correo = ?", user_data.rut, user_data.correo)
    existing_user = cursor.fetchone()

    if existing_user:
        if existing_user.rut == user_data.rut and existing_user.id_rol == ROLE_PROVEEDOR:
            if existing_user.correo != user_data.correo:
                cursor.execute("SELECT id_usuario FROM Usuarios WHERE correo = ?", user_data.correo)
                if cursor.fetchone():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El nuevo correo electrónico ya está en uso.")
            try:
                # Actualizamos rol y datos, y también token_valido_desde
                cursor.execute(
                    """
                    UPDATE Usuarios SET id_rol = ?, nombres = ?, primer_apellido = ?, segundo_apellido = ?, correo = ?,
                           direccion = ?, genero = ?, fecha_nacimiento = ?, token_valido_desde = GETUTCDATE()
                    WHERE id_usuario = ?
                    """, ROLE_HYBRID, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                    user_data.correo, user_data.direccion, user_data.genero, user_data.fecha_nacimiento, existing_user.id_usuario)
                conn.commit()
                # Consultamos la foto actualizada por si acaso (aunque no debería cambiar aquí)
                cursor.execute("SELECT foto_url FROM Usuarios WHERE id_usuario = ?", existing_user.id_usuario)
                updated_user_record = cursor.fetchone()
                foto_url_final = updated_user_record.foto_url if updated_user_record else existing_user.foto_url

            except pyodbc.Error as e:
                conn.rollback(); raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error al actualizar rol: {e}")
            finally:
                cursor.close()
            # Devolvemos UserPublic completo
            return UserPublic(id=str(existing_user.id_usuario), nombres=user_data.nombres, primer_apellido=user_data.primer_apellido,
                              segundo_apellido=user_data.segundo_apellido, rut=user_data.rut, correo=user_data.correo,
                              direccion=user_data.direccion, rol="híbrido", foto_url=foto_url_final,
                              genero=user_data.genero, fecha_nacimiento=user_data.fecha_nacimiento)
        else:
            cursor.close(); raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El RUT o correo ya está registrado.")
    else:
        hashed_password = get_password_hash(user_data.password)
        try:
            # Insertamos con GETUTCDATE() para token_valido_desde
            cursor.execute(
                """
                INSERT INTO Usuarios (rut, nombres, primer_apellido, segundo_apellido, correo, contrasena, direccion, id_rol, estado, genero, fecha_nacimiento, token_valido_desde)
                OUTPUT INSERTED.id_usuario, INSERTED.foto_url, INSERTED.rut, INSERTED.segundo_apellido, INSERTED.direccion
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETUTCDATE())
                """,
                user_data.rut, user_data.nombres, user_data.primer_apellido, user_data.segundo_apellido,
                user_data.correo, hashed_password, user_data.direccion, ROLE_CLIENTE, STATUS_ACTIVO,
                user_data.genero, user_data.fecha_nacimiento
            )
            result = cursor.fetchone()
            new_user_id, new_user_foto_url, inserted_rut, inserted_segundo_apellido, inserted_direccion = result[0], result[1], result[2], result[3], result[4]

            # Creamos perfil vacío solo si es necesario (ajustar si la lógica cambió)
            cursor.execute("INSERT INTO Perfil (id_usuario) VALUES (?)", new_user_id)
            conn.commit()
        except pyodbc.Error as e:
            conn.rollback(); raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en BBDD: {e}")
        finally:
            cursor.close()

        # Devolvemos UserPublic completo
        return UserPublic(id=str(new_user_id), nombres=user_data.nombres, primer_apellido=user_data.primer_apellido,
                          segundo_apellido=inserted_segundo_apellido, rut=inserted_rut, correo=user_data.correo,
                          direccion=inserted_direccion, rol="cliente", foto_url=new_user_foto_url,
                          genero=user_data.genero, fecha_nacimiento=user_data.fecha_nacimiento)


@app.post("/auth/login", response_model=TokenResponse, tags=["Autenticación y Usuarios"])
def login_for_access_token(
        form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
        conn: pyodbc.Connection = Depends(get_db_connection)
):
    correo_usuario = form_data.username
    password_usuario = form_data.password

    cursor = conn.cursor()
    # Traemos todos los campos necesarios para UserPublic
    cursor.execute(
        """
        SELECT id_usuario, nombres, primer_apellido, segundo_apellido, rut,
               contrasena, direccion, id_rol, estado, foto_url, genero, fecha_nacimiento,
               token_valido_desde
        FROM Usuarios WHERE correo = ?
        """,
        correo_usuario
    )
    user_record = cursor.fetchone()

    if not user_record or not verify_password(password_usuario, user_record.contrasena):
        cursor.close(); raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    if user_record.estado != STATUS_ACTIVO:
        cursor.close(); raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La cuenta no está activa.")

    try:
        # Usar GETUTCDATE() para consistencia
        cursor.execute("UPDATE Usuarios SET token_valido_desde = GETUTCDATE() WHERE id_usuario = ?", user_record.id_usuario)
        conn.commit()
    except pyodbc.Error as e:
        conn.rollback(); cursor.close(); raise HTTPException(status_code=500, detail=f"No se pudo actualizar la sesión: {e}")
    cursor.close()

    rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(user_record.id_rol, "desconocido")
    access_token = create_access_token(data={"sub": str(user_record.id_usuario), "rol": rol_str})

    # Construimos el UserPublic completo
    usuario_publico = UserPublic(
        id=str(user_record.id_usuario),
        nombres=user_record.nombres,
        primer_apellido=user_record.primer_apellido,
        segundo_apellido=user_record.segundo_apellido,
        rut=user_record.rut,
        correo=correo_usuario,
        direccion=user_record.direccion,
        rol=rol_str,
        foto_url=user_record.foto_url,
        genero=user_record.genero,
        fecha_nacimiento=user_record.fecha_nacimiento
    )
    return TokenResponse(token=access_token, usuario=usuario_publico)

@app.get("/users/me", response_model=UserPublic, tags=["Autenticación y Usuarios"])
def read_users_me(current_user: UserInDB = Depends(get_current_active_user)):
    """Devuelve los datos públicos COMPLETOS del usuario autenticado."""
    rol_map = {0: "administrador", 1: "cliente", 2: "prestador", 3: "híbrido"}
    rol_str = rol_map.get(current_user.id_rol, "desconocido")

    # Mapeamos TODOS los campos desde UserInDB a UserPublic
    return UserPublic(
        id=str(current_user.id_usuario),
        nombres=current_user.nombres,
        primer_apellido=current_user.primer_apellido,
        segundo_apellido=current_user.segundo_apellido,
        rut=current_user.rut,
        correo=current_user.correo,
        direccion=current_user.direccion,
        rol=rol_str,
        foto_url=current_user.foto_url,
        genero=current_user.genero,
        fecha_nacimiento=current_user.fecha_nacimiento
    )