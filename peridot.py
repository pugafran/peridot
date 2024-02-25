import os
import json
from cryptography.fernet import Fernet
from pathlib import Path

# Genera una clave de encriptación
key = Fernet.generate_key()
cipher_suite = Fernet(key)

# Define el directorio de los dotfiles y el archivo de salida
backup_dir = Path.home() / 'dotfiles_backup'
output_file = Path.home() / 'dotfiles.peridot'
os.makedirs(backup_dir, exist_ok=True)

dotfiles = {}

# Recopila los dotfiles
for item in Path.home().iterdir():
    if item.is_file() and item.name.startswith('.'):
        with open(item, 'rb') as file:
            # Encripta el contenido del archivo
            encrypted_data = cipher_suite.encrypt(file.read())
            dotfiles[item.name] = encrypted_data.decode('utf-8')

# Guarda los dotfiles encriptados en un archivo .peridot
with open(output_file, 'w') as file:
    json.dump(dotfiles, file)

# Guarda la clave en un lugar seguro
with open(Path.home() / 'peridot_key.key', 'wb') as key_file:
    key_file.write(key)

print(f"Los dotfiles han sido respaldados y encriptados en {output_file}")
