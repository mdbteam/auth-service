# app/database.py

import pyodbc
import os
from fastapi import HTTPException, status

CONNECTION_STRING = os.environ.get("DATABASE_CONNECTION_STRING")


def get_db_connection():
    if not CONNECTION_STRING:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La cadena de conexión a la base de datos no está configurada."
        )

    conn = None
    try:
        conn = pyodbc.connect(CONNECTION_STRING, autocommit=False)
        yield conn
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        print(f"Error de conexión a SQL Server: {sqlstate}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo conectar a la base de datos."
        )
    finally:
        if conn:
            conn.close()