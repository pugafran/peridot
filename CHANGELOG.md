# Changelog

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
