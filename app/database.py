# app/database.py

import pyodbc

# Servidor cloud
CONNECTION_STRING = r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=34.31.44.214;DATABASE=Test1;UID=sqlserver;PWD=E]$(aav<0zno6S$_;TrustServerCertificate=yes"
#CONNECTION_STRING = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost,1433;DATABASE=authdb;UID=sa;PWD=MiPassSegura123!"


class SQLDatabase:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    def get_connection(self):
        try:
            conn = pyodbc.connect(self.connection_string)
            return conn
        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            print(f"Error de conexión a SQL Server: {sqlstate}")
            raise Exception(f"No se pudo conectar a la base de datos SQL Server. SQLSTATE: {sqlstate}")

db = SQLDatabase(CONNECTION_STRING)
