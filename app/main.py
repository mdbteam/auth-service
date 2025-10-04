from fastapi import FastAPI, HTTPException, status
from typing import List
from app.models import User, CertificacionCreate, CertificacionResponse # Usar 'app.models'
from app.database import db
from app.utils import hash_password, validar_rut
import pyodbc
from datetime import datetime

app = FastAPI()

USER_FIELDS_SQL = [
    "rut", "nombres", "primer_apellido", "segundo_apellido",
    "correo", "contrasena", "direccion", "rol", "estado", "fecha_creacion"
]


@app.get("/")
def root():
    return {"message": "Auth Service funcionando 🚀"}


@app.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: User):
    if not validar_rut(user.rut):
        raise HTTPException(status_code=400, detail="RUT inválido")

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # ¡ESTA ES LA LÍNEA QUE FALTABA CORREGIR!
        # Debe ser user.correo, NO user.email
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE rut = ? OR correo = ?", user.rut, user.correo)
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Usuario ya registrado (RUT o Correo existente)")

        hashed_pw = hash_password(user.password)
        fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        data = (
            user.rut,
            user.nombres,
            user.primer_apellido,
            user.segundo_apellido,
            user.correo,
            hashed_pw,
            user.direccion,
            user.rol,
            user.estado,
            fecha_creacion
        )

        # 3. Insertar nuevo usuario
        query = f"""
            INSERT INTO Usuarios ({', '.join(USER_FIELDS_SQL)})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.execute(query, data)
        conn.commit()

    except pyodbc.Error as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en la base de datos al registrar: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    return {"message": "Usuario registrado exitosamente"}


@app.get("/users/nombres")
def get_user_nombres():
    conn = db.get_connection()
    cursor = conn.cursor()
    nombres = []

    try:
        cursor.execute("SELECT nombres FROM Usuarios")

        for row in cursor.fetchall():
            nombres.append(row[0])

    except pyodbc.Error as e:
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {e.args[1]}")
    finally:
        cursor.close()
        conn.close()

    return {"count": len(nombres), "nombres": nombres}



@app.post("/certificaciones", status_code=status.HTTP_201_CREATED)
def create_certificacion(cert: CertificacionCreate):
    """Guarda una nueva certificación para un usuario."""
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

        # Mapear los resultados
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