import os
import sys
import json
from cryptography.fernet import Fernet
from pathlib import Path

def encrypt_dotfiles(key, backup_dir, output_file, group_name, files_to_backup):
    cipher_suite = Fernet(key)
    dotfiles_data = {}

    # Carga los datos existentes si el archivo ya existe para no sobrescribir otros grupos
    if output_file.exists():
        with open(output_file, 'r') as file:
            dotfiles_data = json.load(file)

    dotfiles_data[group_name] = {}

    for item in files_to_backup:
        if item.is_file() and item.name.startswith('.'):
            with open(item, 'rb') as file:
                encrypted_data = cipher_suite.encrypt(file.read())
                dotfiles_data[group_name][item.name] = encrypted_data.decode('utf-8')

    with open(output_file, 'w') as file:
        json.dump(dotfiles_data, file)

def decrypt_dotfiles(key, input_file, group_name):
    cipher_suite = Fernet(key)

    with open(input_file, 'r') as file:
        dotfiles_data = json.load(file)

    if group_name not in dotfiles_data:
        print(f"No se encontró el grupo '{group_name}'.")
        return

    for filename, data in dotfiles_data[group_name].items():
        decrypted_data = cipher_suite.decrypt(data.encode('utf-8'))
        with open(Path.home() / filename, 'wb') as file_to_write:
            file_to_write.write(decrypted_data)

def update_dotfiles(key, output_file, group_name):
    # Reutiliza la función encrypt_dotfiles para el update
    files_to_backup = list(Path.home().glob('.*'))
    encrypt_dotfiles(key, None, output_file, group_name, files_to_backup)

def list_dotfiles(input_file):
    if not input_file.exists():
        print("El archivo .peridot no existe.")
        return

    with open(input_file, 'r') as file:
        dotfiles_data = json.load(file)

    if not dotfiles_data:
        print("No hay grupos en el archivo.")
        return

    for group_name, files in dotfiles_data.items():
        print(f"Grupo: {group_name}")
        for file in files:
            print(f"  - {file}")

def remove_group(input_file, group_name):
    if not input_file.exists():
        print("El archivo .peridot no existe.")
        return

    if group_name == "*":
        os.remove(input_file)
        print("Todos los grupos han sido eliminados y el archivo .peridot ha sido borrado.")
        return

    with open(input_file, 'r') as file:
        dotfiles_data = json.load(file)

    if group_name not in dotfiles_data:
        print(f"No se encontró el grupo '{group_name}' para eliminar.")
        return

    print(f"Estás seguro de que quieres eliminar el grupo '{group_name}'? [y/N]:")
    choice = input().lower()
    if choice == 'y':
        del dotfiles_data[group_name]
        with open(input_file, 'w') as file:
            json.dump(dotfiles_data, file)
        print(f"El grupo '{group_name}' ha sido eliminado.")
    else:
        print("Eliminación cancelada.")


def main():
    peridot_file = Path.home() / 'dotfiles.peridot'
    key_file = Path.home() / 'peridot_key.key'

    if len(sys.argv) < 2:
        print("Uso: script.py [encrypt|decrypt|update|list|rm] [nombre_grupo]")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action in ['encrypt', 'decrypt', 'update', 'rm'] and len(sys.argv) != 3:
        print(f"Uso: script.py {action} [nombre_grupo]")
        sys.exit(1)

    group_name = sys.argv[2] if len(sys.argv) > 2 else ""

    if action in ['encrypt', 'update']:
        if not key_file.exists() or action == "encrypt":
            key = Fernet.generate_key()
            with open(key_file, 'wb') as key_file_out:
                key_file_out.write(key)
        else:
            with open(key_file, 'rb') as key_file_in:
                key = key_file_in.read()

        files_to_backup = list(Path.home().glob('.*'))
        if action == 'update' and not peridot_file.exists():
            print("No hay archivo .peridot existente para actualizar. Creando uno nuevo.")
        encrypt_dotfiles(key, peridot_file, peridot_file, group_name, files_to_backup)  # backup_dir no se está utilizando en la función, pero debería pasar peridot_file como output_file.
        print(f"Los dotfiles han sido encriptados/actualizados en el grupo '{group_name}' y guardados en {peridot_file}")
    elif action == 'decrypt':
        if not key_file.exists():
            print("No se encontró la clave de encriptación.")
            sys.exit(1)

        with open(key_file, 'rb') as key_file_in:
            key = key_file_in.read()
        decrypt_dotfiles(key, peridot_file, group_name)
        print(f"Los dotfiles del grupo '{group_name}' han sido desencriptados y restaurados.")
    elif action == 'list':
        list_dotfiles(peridot_file)
    elif action == 'rm':
        remove_group(peridot_file, group_name)
    else:
        print("Acción no reconocida. Use 'encrypt', 'decrypt', 'update', 'list', o 'rm'.")


if __name__ == '__main__':
    main()