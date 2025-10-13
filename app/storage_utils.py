# app/storage_utils.py

import uuid
import os
import shutil
from fastapi import UploadFile
from typing import Optional

# La URL base de tu bucket (se usa para armar el link, aunque es simulación)
GCS_BASE_URL = "https://storage.googleapis.com/chambee_test_1/"


def upload_to_gcs_and_get_url(file: UploadFile, user_id: int, file_type: str) -> str:
    """
    Función que SIMULA la subida de un archivo a GCS y devuelve la URL pública.
    Los archivos se guardan localmente en la carpeta 'uploads/'.
    """

    file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'dat'

    if file_type == "perfil":
        folder_name = "perfiles"
        file_prefix = f"user_{user_id}_profile"
    elif file_type == "portafolio":
        folder_name = f"portafolio/{user_id}"
        file_prefix = f"portfolio_{user_id}"
    elif file_type == "certificados":
        folder_name = f"certificados/{user_id}"
        file_prefix = f"cert_{user_id}"
    else:
        folder_name = "otros"
        file_prefix = "file"

    unique_name = f"{file_prefix}_{uuid.uuid4().hex[:8]}.{file_extension}"
    gcs_simulated_path = f"{folder_name}/{unique_name}"

    # --- SIMULACIÓN DE SUBIDA LOCAL ---
    local_folder_path = f"uploads/{folder_name}"
    os.makedirs(local_folder_path, exist_ok=True)

    local_file_path = f"uploads/{gcs_simulated_path}"

    with open(local_file_path, "wb") as buffer:
        # Rebobinar el archivo para asegurar que se lee desde el inicio
        file.file.seek(0)
        shutil.copyfileobj(file.file, buffer)
    # --- FIN SIMULACIÓN ---

    # 2. Construir la URL pública (usando la URL base de GCS)
    return GCS_BASE_URL + gcs_simulated_path