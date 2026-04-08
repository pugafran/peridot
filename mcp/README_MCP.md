# Peridot MCP (Model Context Protocol)

A stdio MCP server that exposes Peridot as a set of tools so an AI agent can use Peridot without the user having to learn the CLI.

Peridot is a secure dotfiles/config manager: it **packages, encrypts (AES-GCM), and compresses** configuration files into a `.peridot` bundle, and can then inspect/verify/diff and apply it on another machine safely.

## Run

When installed via pipx/pip:

```bash
peridot-mcp
```

or directly with Python:

```bash
python -m peridot_mcp
```

## Protocol

Stdio JSON-RPC with:
- `initialize`
- `tools/list`
- `tools/call`

## Security note

`peridot_apply` is guarded and requires explicit confirmation (`confirm=true`). Use `peridot_apply_dry_run` first.
