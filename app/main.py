from fastapi import FastAPI, HTTPException
from app.models import User
from app.database import users_collection
from app.utils import hash_password, validar_rut

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Auth Service funcionando 🚀"}

@app.post("/register")
def register(user: User):
    if not validar_rut(user.rut):
        raise HTTPException(status_code=400, detail="RUT inválido")
     # Revisar si ya existe el RUT
    if users_collection.find_one({"rut": user.rut}):
        raise HTTPException(status_code=400, detail="Usuario ya registrado")

    # Revisar si ya existe el email
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    # Hashear la contraseña
    hashed_pw = hash_password(user.password)

    new_user = {
        "nombre": user.nombre,
        "apellido": user.apellido,
        "rut": user.rut,
        "email": user.email,
        "password": hashed_pw
    }
    users_collection.insert_one(new_user)

    return {"message": "Usuario registrado exitosamente"}

@app.get("/users/nombres")
def get_user_nombres():
    projection = {"_id": 0, "nombre": 1}
    cursor = users_collection.find({}, projection)
    nombres = [doc.get("nombre") for doc in cursor if doc.get("nombre")]
    return {"count": len(nombres), "nombres": nombres}