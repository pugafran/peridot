#!/usr/bin/env python3

import os
import sys
import json
from cryptography.fernet import Fernet
from pathlib import Path
from threading import Thread
from queue import Queue
from multiprocessing import Value, Lock


def get_total_files(paths_to_backup):
    total_files = 0
    for path in paths_to_backup:
        if path.is_file():
            total_files += 1
        elif path.is_dir() and not path.is_symlink():
            for root, _, files in os.walk(path):
                # Asegúrate de contar solo archivos regulares, excluyendo sockets y symlinks
                for file in files:
                    file_path = Path(root) / file
                    if not file_path.is_socket() and not file_path.is_symlink():
                        total_files += 1
    return total_files


def encrypt_file(path, cipher_suite, dotfiles_data, group_name, file_count, total_files, lock):
    try:
        with open(path, 'rb') as file:
            encrypted_data = cipher_suite.encrypt(file.read())
            with lock:
                relative_path = str(path.relative_to(Path.home()))
                dotfiles_data[group_name][relative_path] = encrypted_data.decode('utf-8')
                file_count.value += 1
                progress = (file_count.value / total_files) * 100
                print(f"\rProcesado archivo {file_count.value}/{total_files} - Encriptando: {progress:.2f}%", end='')
    except Exception as e:
        print(f"\nError al procesar el archivo {path}: {e}")




def worker(cipher_suite, dotfiles_data, group_name, file_queue, file_count, total_files, lock):
    while True:
        path = file_queue.get()
        if path is None:  # Señal de parada para el hilo
            break
        if path.is_file() and not path.is_socket():
            encrypt_file(path, cipher_suite, dotfiles_data, group_name, file_count, total_files, lock)
        file_queue.task_done()

def encrypt_dotfiles(key, output_file, group_name, paths_to_backup):
    cipher_suite = Fernet(key)
    dotfiles_data = {}

    if output_file.exists():
        with open(output_file, 'r') as file:
            existing_data = json.load(file)
            dotfiles_data.update(existing_data)

    dotfiles_data.setdefault(group_name, {})
    file_queue = Queue()
    lock = Lock()

    total_files = get_total_files(paths_to_backup)
    file_count = Value('i', 0)

    # Asegurarse de que el contador se inicializa correctamente
    print(f"Total de archivos a procesar: {total_files}")

    threads = []
    for _ in range(1):
        thread = Thread(target=worker, args=(cipher_suite, dotfiles_data, group_name, file_queue, file_count, total_files, lock))
        thread.start()
        threads.append(thread)

    for path in paths_to_backup:
        if path.is_file():
            file_queue.put(path)
        elif path.is_dir() and not path.is_symlink():
            for root, _, files in os.walk(path):
                # Asegurarse de añadir todos los archivos del directorio y subdirectorios
                for file in files:
                    file_path = Path(root) / file
                    if not file_path.is_socket() and not file_path.is_symlink():
                        file_queue.put(file_path)

    file_queue.join()

    for _ in threads:
        file_queue.put(None)
    for thread in threads:
        thread.join()

    with open(output_file, 'w') as file:
        json.dump(dotfiles_data, file)




def update_dotfiles(key, output_file, group_name):
    # Reutiliza la función encrypt_dotfiles para el update
    files_to_backup = list(Path.home().glob('.*'))
    encrypt_dotfiles(key, None, output_file, group_name, files_to_backup)

def list_dotfiles(input_file, detailed=False):
    if not input_file.exists():
        print("El archivo .peridot no existe.")
        return

    with open(input_file, 'r') as file:
        dotfiles_data = json.load(file)

    if not dotfiles_data:
        print("No hay grupos en el archivo.")
        return

    for group_name, paths in dotfiles_data.items():
        print(f"Grupo: {group_name}")
        if detailed:
            for path in sorted(paths):
                print(f"  - {path}")
        else:
            # Solo muestra los directorios raíz y archivos en el nivel superior del grupo
            root_items = set()
            for path in paths:
                root_item = path.split('/')[0]
                root_items.add(root_item)
            for item in sorted(root_items):
                print(f"  - {item}")


def remove_group(input_file, group_name):
    if not input_file.exists():
        print("El archivo .peridot no existe.")
        return

    if group_name == '*':
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
        print("Uso: script.py [encrypt|decrypt|update|list|rm] [nombre_grupo] [-t]")
        sys.exit(1)

    action = sys.argv[1].lower()
    detailed = '-t' in sys.argv

    if action == 'list':
        list_dotfiles(peridot_file, detailed)
    else:
        if len(sys.argv) < 3:
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

            # Definir archivos y directorios a respaldar
            paths_to_backup = [p for p in Path.home().glob('.*') if p.is_file() or (p.is_dir() and not p.is_symlink())]

            # Llamar a la función de encriptación
            encrypt_dotfiles(key, peridot_file, group_name, paths_to_backup)
            print(f"Los dotfiles han sido encriptados/actualizados en el grupo '{group_name}' y guardados en {peridot_file}")
        elif action == 'decrypt':
            if not key_file.exists():
                print("No se encontró la clave de encriptación.")
                sys.exit(1)

            with open(key_file, 'rb') as key_file_in:
                key = key_file_in.read()
            decrypt_dotfiles(key, peridot_file, group_name)
            print(f"Los dotfiles del grupo '{group_name}' han sido desencriptados y restaurados.")
        elif action == 'rm':
            remove_group(peridot_file, group_name)

if __name__ == '__main__':
    main()