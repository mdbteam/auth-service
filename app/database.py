from pymongo import MongoClient

# URI que copiaste de Atlas (reemplaza )
MONGO_URI = "mongodb+srv://bayrfuentes:lfpfrhh6aJnBkWrN@cluster0.gell6mj.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(MONGO_URI)
db = client["authdb"]              # Base de datos
users_collection = db["users"]     # Colección de usuarios
