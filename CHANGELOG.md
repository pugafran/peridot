# Changelog

## 0.4.5 - 2026-04-11

- pack: safer defaults (exclude common dev dirs, VCS metadata) and improved sensitive-path detection (SSH/AWS/Docker/Git).
- cli: `init --json` output; ensure `--json` outputs are clean (no locale tips in stdout).
- i18n/windows: better locale normalization + `PERIDOT_LANG=auto/system`; improved shell detection in env.
- doctor: report zstandard (zstd) availability; improve dependency hints and error output without Rich.

## 0.4.4 - 2026-04-09

- pack: skip unreadable/protected files instead of crashing (e.g. `~/.ssh/config` on Windows); record skipped files in manifest and expose `skipped` in `pack --json`.
- ui: improve output when no local `.peridot` bundles are found (avoid truncated table row).

## 0.4.3 - 2026-04-09

- MCP: add `peridot-mcp` server and expand tools coverage.
- MCP/CLI: JSON-only outputs for machine consumption (`pack/inspect/diff/verify/bench`).
- Apply: two-phase safety with `apply_token` (`apply --dry-run --json` → token; `apply --json` validates `--apply-token`).
- Apply: hardening (avoid writing through existing symlinks; preserve symlinks in backups/rollback).
- Security: mark `.netrc` and `.pypirc` as sensitive.
- Windows: improve shell detection for COMSPEC backslash paths.

## 0.4.2 - 2026-04-08

- Windows: include both PowerShell 7+ (Documents/PowerShell) and Windows PowerShell legacy (Documents/WindowsPowerShell) profile paths (including OneDrive variants).

## 0.4.1 - 2026-04-08

- Packaging: prepare PyPI publishing (README.md casing + project URLs).
- CI: add publish workflow for tags v* (uses PYPI_API_TOKEN).

## 0.4.0 - 2026-04-08

- pack: significant speedup by writing encrypted payloads directly into the output ZIP (avoids temp payload files).
- pack: smarter compression heuristics (skip compression for high-entropy payloads).
- apply: transactional rollback (best-effort) + verify-on-write (hash check after writing; rollback on mismatch).
- cli: new commands `init` (bootstrap key + settings) and `bench` (benchmarks with throughput/ratio + JSON output).
- ci: expanded GitHub Actions matrix (linux/macos/windows × Python 3.11/3.12) using editable install + dev extras.
- docs: quickstart, CI badge, improved install/dev instructions.

## 0.3.0 - 2026-03-17

- Rebuilt Peridot as a richer CLI-first tool for creating, inspecting, applying and managing `.peridot` bundles.
- Added interactive `settings`, visual `ui`, categorized catalog, presets, profiles, doctor, diff, verify, history, merge and split workflows.
- Improved packing performance with adaptive file scanning feedback, smarter concurrency control, adaptive per-file compression and a non-recompressing outer bundle container.
- Standardized bundle encryption on AES-GCM per file and removed legacy Fernet support from the active format.
- Switched Peridot compression to prefer `zstd`, with automatic `gzip` fallback when `zstandard` is unavailable in the current Python.
- Added install metadata, packaging support, install script, license and repository hygiene files for publishing on GitHub.
