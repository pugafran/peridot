# Peridot MCP (Model Context Protocol)

Servidor MCP (stdio) que expone Peridot como un conjunto de *tools* para que una IA pueda gestionar Peridot sin que el usuario aprenda el CLI.

Peridot sirve para **empaquetar, cifrar (AES-GCM) y comprimir** dotfiles/ficheros de configuración en un bundle `.peridot`, inspeccionarlo/verificarlo y aplicarlo en otra máquina de forma segura.

## Ejecutar

Instalado via pipx/pip:

```bash
peridot-mcp
```

o directamente con Python:

```bash
python -m peridot_mcp
```

## Protocolo

Servidor stdio (JSON-RPC) con métodos:
- `initialize`
- `tools/list`
- `tools/call`

## Nota de seguridad

En el MVP, no se expone `apply` real. Cuando se implemente, será **opt-in** y requerirá confirmación explícita.
