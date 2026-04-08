# Peridot MCP (Model Context Protocol)

Este directorio documenta el servidor MCP de Peridot.

Objetivo: exponer Peridot como un conjunto de *tools* para que un agente (IA) pueda:
- inicializar (`peridot_init`)
- listar presets (`peridot_presets_list`)
- obtener versión (`peridot_version`)

sin que el usuario tenga que aprender el CLI.

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
