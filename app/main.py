# app/main.py

from fastapi import FastAPI, HTTPException, status, Form, UploadFile, File, Depends
from typing import List, Optional
from app.models import (
    User, CertificacionCreate, CertificacionResponse,
    Login, PrestadorResumen, PrestadorDetalle, PostulacionForm,
    TokenResponse, Resena, Servicio, Rating
)
from app.database import db
from app.utils import hash_password, validar_rut
from app.storage_utils import upload_to_gcs_and_get_url  # ¡Simulación!
import pyodbc
from datetime import datetime
from jose import jwt
from passlib.context import CryptContext
import os

# Configuración de Seguridad
SECRET_KEY = os.environ.get("SECRET_KEY", "tu-clave-secreta-debe-cambiar")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

# Constantes de Roles y Estados
ROLE_CLIENTE = 1
ROLE_PROVEEDOR = 2
ROLE_HYBRID = 3
STATUS_ACTIVO = 'activo'
STATUS_PENDIENTE = 'pendiente'
STATUS_CAMPOS_SQL = ['rut', 'nombres', 'primer_apellido', 'segundo_apellido', 'correo',
                     'contrasena', 'direccion', 'id_rol', 'estado', 'fecha_creacion']

# URL base
BASE_URL = os.environ.get("BASE_URL", "http://localhost:10000")


# --- Funciones de Seguridad ---

def verify_password(plain_password, hashed_password):
    return hash_password(plain_password) == hashed_password


def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# --- ENDPOINT: Raíz ---

@app.get("/")
def root():
    return {"message": "Auth Service funcionando 🚀"}


# =========================================================================
# 1. AUTENTICACIÓN Y USUARIOS
# =========================================================================

# 1.1 REGISTRO DE CLIENTE (POST /api/auth/register)
@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_client(user: User):
    if not validar_rut(user.rut):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="RUT inválido")

    conn = db.get_connection()
    cursor = conn.cursor()
    assigned_id_rol = None
    new_user_id = None

    try:
        cursor.execute("SELECT id_usuario, id_rol FROM Usuarios WHERE rut = ? OR correo = ?", user.rut, user.correo)
        existing_user = cursor.fetchone()

        if existing_user:
            user_id_exist, id_rol_exist = existing_user

            if id_rol_exist == ROLE_PROVEEDOR:
                assigned_id_rol = ROLE_HYBRID
                new_user_id = user_id_exist
                update_query = "UPDATE Usuarios SET id_rol = ?, estado = ? WHERE id_usuario = ?"
                cursor.execute(update_query, assigned_id_rol, STATUS_ACTIVO, user_id_exist)

            elif id_rol_exist in [ROLE_CLIENTE, ROLE_HYBRID]:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="El RUT o correo ya se encuentra registrado.")
            else:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usuario ya se encuentra registrado.")

        else:
            assigned_id_rol = ROLE_CLIENTE
            hashed_pw = hash_password(user.password)
            fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            data = (user.rut, user.nombres, user.primer_apellido, user.segundo_apellido, user.correo,
                    hashed_pw, user.direccion, assigned_id_rol, STATUS_ACTIVO, fecha_creacion)

            query = f"INSERT INTO Usuarios ({', '.join(STATUS_CAMPOS_SQL)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            cursor.execute(query, data)

            cursor.execute("SELECT SCOPE_IDENTITY()")
            new_user_id = cursor.fetchone()[0]

        conn.commit()

    except pyodbc.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El RUT o correo ya existe en el sistema.")
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error inesperado al registrar: {e}")
    finally:
        cursor.close()
        conn.close()

    rol_str = {ROLE_CLIENTE: "cliente", ROLE_HYBRID: "ambos"}.get(assigned_id_rol)

    return {
        "id": str(new_user_id),
        "nombres": user.nombres,
        "correo": user.correo,
        "rol": rol_str
    }


# 1.2 INICIO DE SESIÓN (POST /api/auth/login)
@app.post("/auth/login", status_code=status.HTTP_200_OK, response_model=TokenResponse)
def login_user(credentials: Login):
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id_usuario, nombres, contrasena, id_rol, estado FROM Usuarios WHERE correo = ?",
                       credentials.correo)
        user_record = cursor.fetchone()

        if not user_record:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

        user_id, nombres, hashed_password, id_rol, estado = user_record

        if not verify_password(credentials.password, hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas.")

        if estado == 'rechazado':
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Cuenta rechazada. Contacte a soporte.")

        rol_map = {ROLE_CLIENTE: "cliente", ROLE_PROVEEDOR: "prestador", ROLE_HYBRID: "ambos"}
        rol_str = rol_map.get(id_rol, "desconocido")

        access_token = create_access_token(data={"sub": str(user_id), "rol": rol_str})

        return {
            "token": access_token,
            "usuario": {
                "id": str(user_id),
                "nombres": nombres,
                "rol": rol_str
            }
        }

    except Exception as e:
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error inesperado al iniciar sesión: {e}")
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# 2. PRESTADORES (Lectura)
# =========================================================================

# 2.1 OBTENER LISTA DE TODOS LOS PRESTADORES (GET /api/prestadores)
@app.get("/prestadores", response_model=List[PrestadorResumen])
def get_all_prestadores():
    conn = db.get_connection()
    cursor = conn.cursor()
    prestadores = []

    try:
        # Consulta compleja: Usuarios + Perfil + Oficio + Valoraciones
        query = """
            SELECT 
                U.id_usuario, U.nombres, U.primer_apellido, P.foto_url, P.descripcion, 
                AVG(V.puntaje) AS puntuacion_promedio, 
                STRING_AGG(O.nombre_oficio, ',') AS lista_oficios 
            FROM Usuarios U
            LEFT JOIN Perfil P ON U.id_usuario = P.id_usuario
            LEFT JOIN Valoraciones V ON U.id_usuario = V.id_usuario 
            LEFT JOIN Oficio O ON U.id_usuario = O.id_usuario
            WHERE U.id_rol IN (?, ?) AND U.estado = ?
            GROUP BY U.id_usuario, U.nombres, U.primer_apellido, P.foto_url, P.descripcion
            ORDER BY U.id_usuario;
        """
        cursor.execute(query, ROLE_PROVEEDOR, ROLE_HYBRID, STATUS_ACTIVO)

        for row in cursor.fetchall():
            prestadores.append({
                "id": str(row[0]),
                "nombres": row[1],
                "primer_apellido": row[2],
                "fotoUrl": row[3] if row[3] else "/assets/images/default.webp",
                # CORREGIDO: Dividir la cadena de oficios en una lista
                "oficios": row[6].split(',') if row[6] else [],
                "resumen": row[4] if row[4] else "Especialista no ha añadido descripción de trabajo.",
                "puntuacion": float(row[5]) if row[5] is not None else 0.0
            })

        return prestadores

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error al obtener prestadores: {e}")
    finally:
        cursor.close()
        conn.close()


# 2.2 OBTENER PERFIL DETALLADO DE UN PRESTADOR (GET /api/prestadores/{id})
@app.get("/prestadores/{user_id}", response_model=PrestadorDetalle)
def get_prestador_detalle(user_id: int):
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 1. Obtener datos básicos, Perfil, y Oficios
        cursor.execute("""
            SELECT 
                U.id_usuario, U.nombres, U.primer_apellido, U.segundo_apellido, 
                P.biografia, P.descripcion, P.foto_url, 
                STRING_AGG(O.nombre_oficio, ',') AS lista_oficios,
                (SELECT COUNT(*) FROM Certificaciones C WHERE C.id_usuario = U.id_usuario) AS tiene_certificaciones 
            FROM Usuarios U
            LEFT JOIN Perfil P ON U.id_usuario = P.id_usuario
            LEFT JOIN Oficio O ON U.id_usuario = O.id_usuario
            WHERE U.id_usuario = ? AND U.id_rol IN (?, ?) AND U.estado = ?
            GROUP BY U.id_usuario, U.nombres, U.primer_apellido, U.segundo_apellido, P.biografia, P.descripcion, P.foto_url;
        """, user_id, ROLE_PROVEEDOR, ROLE_HYBRID, STATUS_ACTIVO)

        user_data = cursor.fetchone()
        if not user_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prestador no encontrado.")

        (id, nombres, primer_apellido, segundo_apellido, biografia, descripcion_trabajo, foto_url, oficios_str,
         tiene_certificaciones) = user_data

        # 2. Obtener Reseñas y Puntuaciones
        cursor.execute("""
            SELECT AVG(puntaje), COUNT(*) 
            FROM Valoraciones WHERE id_usuario = ?;
        """, id)
        puntuacion_data = cursor.fetchone()
        puntuacion = float(puntuacion_data[0]) if puntuacion_data and puntuacion_data[0] is not None else 0.0
        total_resenas = int(puntuacion_data[1]) if puntuacion_data and puntuacion_data[1] is not None else 0

        # 3. Obtener Portafolio (enlaces)
        cursor.execute("SELECT enlace FROM Portafolio WHERE id_usuario = ?", id)
        portafolio_links = [row[0] for row in cursor.fetchall()]

        # 4. Obtener Reseñas (Detalle)
        cursor.execute("""
            SELECT V.id_valoracion, U.nombres, V.puntaje, V.comentario
            FROM Valoraciones V
            JOIN Usuarios U ON V.id_usuario_autor = U.id_usuario
            WHERE V.id_usuario = ?
            ORDER BY V.fecha_creacion DESC
        """, id)
        resenas_db = cursor.fetchall()

        resenas_list = [
            Resena(id=str(r[0]), autor=r[1], puntuacion=r[2], comentario=r[3])
            for r in resenas_db
        ]

        # 5. Distribución de Puntuación (Simulación)
        rating_distribution_simulado = [Rating(stars=5, count=10), Rating(stars=4, count=2)]
        servicios_simulados = [Servicio(id="s1", nombre="Reparación de Fugas", precioEstimado="$25.000")]

        # Construir la Respuesta
        return {
            "id": str(id),
            "nombres": nombres,
            "primer_apellido": primer_apellido,
            "segundo_apellido": segundo_apellido,
            "fotoUrl": foto_url if foto_url else "/assets/images/default.webp",
            # CORREGIDO: Usar la lista de oficios
            "oficios": oficios_str.split(',') if oficios_str else [],
            # CORREGIDO: Usar nombres de campo correctos
            "biografia_personal": biografia if biografia else "Sin biografía personal.",
            "descripcion_trabajo": descripcion_trabajo if descripcion_trabajo else "Sin descripción de trabajos.",
            "estaVerificado": bool(tiene_certificaciones),
            "puntuacion": puntuacion,
            "totalReseñas": total_resenas,
            "servicios": servicios_simulados,
            "reseñas": resenas_list,
            "ratingDistribution": rating_distribution_simulado,
            "portafolio_links": portafolio_links
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error al obtener detalle del prestador: {e}")
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# 3. POSTULACIÓN A PRESTADOR - CON LÓGICA DE SUBIDA DE ARCHIVOS SIMULADA
# =========================================================================

# 3.1 ENVIAR FORMULARIO DE POSTULACIÓN (POST /api/postulaciones)
@app.post("/postulaciones", status_code=status.HTTP_200_OK)
def send_postulacion(
        form_data: PostulacionForm = Depends(),
        archivos_certificados: List[UploadFile] = File(None),
        archivos_portafolio: List[UploadFile] = File(None),
        foto_perfil: Optional[UploadFile] = File(None)
):
    # SIMULACIÓN DE ID: Reemplazar con ID de JWT en producción
    user_id_autenticado = 10

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 1. Obtener Rol
        cursor.execute("SELECT id_rol FROM Usuarios WHERE id_usuario = ?", user_id_autenticado)
        user_record = cursor.fetchone()

        if not user_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

        id_rol_actual = user_record[0]
        assigned_id_rol = ROLE_HYBRID if id_rol_actual == ROLE_CLIENTE else id_rol_actual

        # 2. SUBIDA DE LA FOTO DE PERFIL (SIMULADA)
        perfil_foto_url = None
        if foto_perfil and foto_perfil.filename:
            perfil_foto_url = upload_to_gcs_and_get_url(
                file=foto_perfil,
                user_id=user_id_autenticado,
                file_type="perfil"
            )

        # 3. ACTUALIZAR PERFIL (Insertar/Actualizar Perfil, incluyendo la foto_url)
        cursor.execute("SELECT id_perfil, foto_url FROM Perfil WHERE id_usuario = ?", user_id_autenticado)
        perfil_record = cursor.fetchone()

        final_foto_url = perfil_foto_url if perfil_foto_url else (
            perfil_record[1] if perfil_record and len(perfil_record) > 1 else None)

        if perfil_record:
            # UPDATE
            update_perfil_query = "UPDATE Perfil SET biografia = ?, descripcion = ?, foto_url = ? WHERE id_usuario = ?"
            cursor.execute(update_perfil_query, form_data.biografia, form_data.descripcion_trabajo, final_foto_url,
                           user_id_autenticado)
        else:
            # INSERT
            insert_perfil_query = "INSERT INTO Perfil (id_usuario, biografia, descripcion, foto_url) VALUES (?, ?, ?, ?)"
            cursor.execute(insert_perfil_query, user_id_autenticado, form_data.biografia, form_data.descripcion_trabajo,
                           final_foto_url)

        # 4. SUBIDA E INSERCIÓN DEL PORTAFOLIO (SIMULADA)
        cursor.execute("DELETE FROM Portafolio WHERE id_usuario = ?", user_id_autenticado)

        for file in archivos_portafolio:
            if file.filename:
                portafolio_link = upload_to_gcs_and_get_url(
                    file=file,
                    user_id=user_id_autenticado,
                    file_type="portafolio"
                )
                # Insertamos la URL de GCS en la tabla Portafolio
                cursor.execute("INSERT INTO Portafolio (id_usuario, descripcion, enlace) VALUES (?, ?, ?)",
                               user_id_autenticado, file.filename, portafolio_link)

                # 5. SUBIDA E INSERCIÓN DE CERTIFICADOS (NUEVO PASO)
        cursor.execute("DELETE FROM Certificaciones WHERE id_usuario = ?", user_id_autenticado)

        for file in archivos_certificados:
            if file.filename:
                cert_link = upload_to_gcs_and_get_url(
                    file=file,
                    user_id=user_id_autenticado,
                    file_type="certificados"
                )
                cert_name = file.filename
                fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # OJO: Se asume que la tabla 'Certificaciones' tiene la columna 'url_documento'
                try:
                    cursor.execute(
                        "INSERT INTO Certificaciones (id_usuario, nombre_certificacion, url_documento, fecha_creacion) VALUES (?, ?, ?, ?)",
                        user_id_autenticado, cert_name, cert_link, fecha_creacion)
                except pyodbc.ProgrammingError:
                    # Si 'url_documento' no existe, usar el insert original
                    cursor.execute(
                        "INSERT INTO Certificaciones (id_usuario, nombre_certificacion, fecha_creacion) VALUES (?, ?, ?)",
                        user_id_autenticado, cert_name, fecha_creacion)

        # 6. INSERTAR OFICIOS (Borrar antiguos e insertar nuevos)
        cursor.execute("DELETE FROM Oficio WHERE id_usuario = ?", user_id_autenticado)

        oficios_list = [o.strip() for o in form_data.oficios_str.split(',') if o.strip()]
        for oficio_nombre in oficios_list:
            cursor.execute("INSERT INTO Oficio (id_usuario, nombre_oficio) VALUES (?, ?)", user_id_autenticado,
                           oficio_nombre)

        # 7. ACTUALIZAR ROL y ESTADO en Usuarios
        update_user_query = "UPDATE Usuarios SET id_rol = ?, estado = ? WHERE id_usuario = ?"
        cursor.execute(update_user_query, assigned_id_rol, STATUS_PENDIENTE, user_id_autenticado)

        conn.commit()

        return {
            "mensaje": "Postulación enviada exitosamente. Quedará pendiente de revisión.",
            "statusPostulacion": STATUS_PENDIENTE
        }

    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Error inesperado al procesar postulación: {e}")
    finally:
        cursor.close()
        conn.close()


# =========================================================================
# ENDPOINTS ANTIGUOS DE CERTIFICACIONES
# =========================================================================

@app.post("/certificaciones", status_code=status.HTTP_201_CREATED)
def create_certificacion(cert: CertificacionCreate):
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