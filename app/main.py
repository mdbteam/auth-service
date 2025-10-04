# app/main.py
from fastapi import FastAPI, HTTPException, status
from typing import List
from app.models import User, CertificacionCreate, CertificacionResponse
from app.database import db
from app.utils import hash_password, validar_rut, generate_verification_token, send_verification_email
import pyodbc
from datetime import datetime
from dotenv import load_dotenv  # Necesario para cargar variables de entorno
import os


# Cargar variables de entorno (desde .env)
load_dotenv()

app = FastAPI()

# Constantes de Roles y Estados
ROLE_CLIENTE = 1
ROLE_PROVEEDOR = 2
ROLE_HYBRID = 3
STATUS_PENDIENTE = 'pendiente'
STATUS_ACTIVO = 'activo'

# ⚠️ CRUCIAL: Se actualiza para la tabla 'Usuarios' con id_rol y verification_token
USER_FIELDS_SQL = [
    "rut", "nombres", "primer_apellido", "segundo_apellido",
    "correo", "contrasena", "direccion", "id_rol", "estado", "fecha_creacion", "verification_token"
]


@app.get("/")
def root():
    return {"message": "Auth Service funcionando 🚀"}


# URL base para el enlace de verificación (AJUSTAR ESTO A TU DOMINIO REAL)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:10000")


# =========================================================================
# ENDPOINT 1: REGISTRO DE CLIENTE (ROL 1 y UPGRADE desde ROL 2 a ROL 3)
# =========================================================================
@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_client(user: User):
    if not validar_rut(user.rut):
        raise HTTPException(status_code=400, detail="RUT inválido")

    conn = db.get_connection()
    cursor = conn.cursor()

    is_update = False
    assigned_id_rol = None
    verification_token = generate_verification_token()

    try:
        # 1. Verificación de existencia y id_rol actual
        cursor.execute("SELECT id_usuario, id_rol FROM Usuarios WHERE rut = ? OR correo = ?", user.rut, user.correo)
        existing_user = cursor.fetchone()

        if existing_user:
            user_id_exist, id_rol_exist = existing_user

            if id_rol_exist == ROLE_PROVEEDOR:
                # CASO UPGRADE: Rol 2 -> Rol 3 (Híbrido)
                is_update = True
                assigned_id_rol = ROLE_HYBRID
                new_user_id = user_id_exist

                update_query = """
                    UPDATE Usuarios SET id_rol = ?, estado = ?, verification_token = ?
                    WHERE id_usuario = ?
                """
                cursor.execute(update_query, assigned_id_rol, STATUS_PENDIENTE, verification_token, user_id_exist)

            elif id_rol_exist == ROLE_CLIENTE:
                # CASO CONFLICTO: Ya es Cliente (Rol 1)
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Usuario ya se encuentra registrado como cliente.")
            else:
                # CASO CONFLICTO: Rol 0, 3 o cualquier otro
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usuario ya se encuentra registrado.")

        else:
            # CASO NUEVO: Rol 1 (Cliente)
            assigned_id_rol = ROLE_CLIENTE

            hashed_pw = hash_password(user.password)
            fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            data = (user.rut, user.nombres, user.primer_apellido, user.segundo_apellido, user.correo,
                    hashed_pw, user.direccion, assigned_id_rol, STATUS_PENDIENTE, fecha_creacion, verification_token)

            query = f"""
                INSERT INTO Usuarios ({', '.join(USER_FIELDS_SQL)})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, data)

            cursor.execute("SELECT SCOPE_IDENTITY()")
            new_user_id = cursor.fetchone()[0]

        # 2. Finalizar transacción
        conn.commit()

        # 3. Envío de Correo (para Roles 1 y 3)
        send_verification_email(user.correo, verification_token, BASE_URL)

    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos al registrar: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    # 4. Respuesta Exitosa
    rol_str = {ROLE_CLIENTE: "cliente", ROLE_HYBRID: "hibrido"}.get(assigned_id_rol)

    return {
        "id": new_user_id,
        "nombres": user.nombres,
        "correo": user.correo,
        "rol": rol_str,
        "message": "Registro/Actualización exitosa. Por favor, verifica tu correo electrónico para activar tu cuenta."
    }


# =========================================================================
# ENDPOINT 2: POSTULACIÓN PROVEEDOR (ROL 2 y UPGRADE desde ROL 1 a ROL 3)
# =========================================================================
@app.post("/postulaciones", status_code=status.HTTP_201_CREATED)
def register_provider(user: User):
    if not validar_rut(user.rut):
        raise HTTPException(status_code=400, detail="RUT inválido")

    conn = db.get_connection()
    cursor = conn.cursor()

    should_send_email = False
    verification_token = generate_verification_token()

    try:
        # 1. Verificación de existencia y id_rol actual
        cursor.execute("SELECT id_usuario, id_rol FROM Usuarios WHERE rut = ? OR correo = ?", user.rut, user.correo)
        existing_user = cursor.fetchone()

        if existing_user:
            user_id_exist, id_rol_exist = existing_user

            if id_rol_exist == ROLE_CLIENTE:
                # CASO UPGRADE: Rol 1 -> Rol 3 (Híbrido)
                assigned_id_rol = ROLE_HYBRID
                should_send_email = True

                # Ejecución del UPDATE
                update_query = """
                    UPDATE Usuarios SET id_rol = ?, estado = ?, verification_token = ?
                    WHERE id_usuario = ?
                """
                cursor.execute(update_query, assigned_id_rol, STATUS_PENDIENTE, verification_token, user_id_exist)
                new_user_id = user_id_exist

            elif id_rol_exist == ROLE_PROVEEDOR:
                # CASO CONFLICTO: Ya es Proveedor (Rol 2)
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Usuario ya se encuentra postulado como proveedor.")
            else:
                # CASO CONFLICTO: Rol 0, 3 o cualquier otro
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usuario ya se encuentra registrado.")

        else:
            # CASO NUEVO: Rol 2 (Proveedor)
            assigned_id_rol = ROLE_PROVEEDOR

            hashed_pw = hash_password(user.password)
            fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            data = (user.rut, user.nombres, user.primer_apellido, user.segundo_apellido, user.correo,
                    hashed_pw, user.direccion, assigned_id_rol, STATUS_PENDIENTE, fecha_creacion, verification_token)

            query = f"""
                INSERT INTO Usuarios ({', '.join(USER_FIELDS_SQL)})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, data)

            cursor.execute("SELECT SCOPE_IDENTITY()")
            new_user_id = cursor.fetchone()[0]

        # 2. Finalizar transacción
        conn.commit()

        # 3. Envío de Correo (solo si es upgrade a Rol 3)
        if should_send_email:
            send_verification_email(user.correo, verification_token, BASE_URL)

    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos al postular: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    # 4. Respuesta Exitosa
    rol_map = {ROLE_PROVEEDOR: "proveedor", ROLE_HYBRID: "hibrido"}
    rol_str = rol_map.get(assigned_id_rol)

    response = {
        "id": new_user_id,
        "nombres": user.nombres,
        "correo": user.correo,
        "rol": rol_str,
    }

    if assigned_id_rol == ROLE_PROVEEDOR:
        response["message"] = "Postulación exitosa. Tu cuenta será revisada y activada manualmente."
    else:  # Rol 3
        response[
            "message"] = "Perfil actualizado a híbrido. Por favor, verifica tu correo electrónico para activar tu cuenta de proveedor/cliente."

    return response


# =========================================================================
# ENDPOINT 3: VERIFICACIÓN DE CORREO (ACTIVACIÓN DE CUENTA)
# =========================================================================
@app.get("/auth/verify", status_code=status.HTTP_200_OK)
def verify_email(token: str):
    """
    Activa la cuenta si el token es válido.
    IGNORA a los usuarios con Rol 2 (Proveedor) ya que su activación es manual.
    """
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 1. Buscar usuario por token
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE verification_token = ?", token)
        user_id = cursor.fetchone()

        if not user_id:
            raise HTTPException(status_code=400, detail="Token de verificación inválido o expirado.")

        # 2. Actualizar estado a ACTIVO y eliminar token
        update_query = """
            UPDATE Usuarios 
            SET estado = ?, verification_token = NULL
            WHERE id_usuario = ? AND id_rol <> ?
        """
        # El token es nulo una vez usado
        cursor.execute(update_query, STATUS_ACTIVO, user_id[0], ROLE_PROVEEDOR)
        conn.commit()

        return {"message": "Cuenta verificada y activada exitosamente."}

    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error al verificar el correo: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# ENDPOINTS ANTIGUOS DE CERTIFICACIONES (Se mantienen)
# =========================================================================

@app.post("/certificaciones", status_code=status.HTTP_201_CREATED)
def create_certificacion(cert: CertificacionCreate):
    """Guarda una nueva certificación para un usuario."""
    # ... (Se mantiene tu código original aquí) ...
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE id_usuario = ?", cert.id_usuario)
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Usuario con id {cert.id_usuario} no encontrado.")

        fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query = """
            INSERT INTO Certificaciones (id_usuario, nombre_certificacion, fecha_creacion)
            VALUES (?, ?, ?)
        """
        cursor.execute(query, cert.id_usuario, cert.nombre_certificacion, fecha_creacion)
        conn.commit()

    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos al guardar certificación: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    return {"message": "Certificación guardada exitosamente"}


@app.get("/certificaciones/{id_usuario}", response_model=List[CertificacionResponse])
def get_certificaciones_by_user(id_usuario: int):
    """Consulta todas las certificaciones de un usuario específico."""
    # ... (Se mantiene tu código original aquí) ...
    conn = db.get_connection()
    cursor = conn.cursor()
    certificaciones = []

    try:
        query = """
            SELECT id_certificacion, id_usuario, nombre_certificacion, fecha_creacion
            FROM Certificaciones
            WHERE id_usuario = ?
        """
        cursor.execute(query, id_usuario)

        for row in cursor.fetchall():
            certificaciones.append(CertificacionResponse(
                id_certificacion=row[0],
                id_usuario=row[1],
                nombre_certificacion=row[2],
                fecha_creacion=row[3].isoformat() if row[3] else None
            ))

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    return certificaciones