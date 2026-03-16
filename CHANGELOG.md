# Changelog

## 0.3.0 - 2026-03-17

- Rebuilt Peridot as a richer CLI-first tool for creating, inspecting, applying and managing `.peridot` bundles.
- Added interactive `settings`, visual `ui`, categorized catalog, presets, profiles, doctor, diff, verify, history, merge and split workflows.
- Improved packing performance with adaptive file scanning feedback, smarter concurrency control, adaptive per-file compression and a non-recompressing outer bundle container.
- Standardized bundle encryption on AES-GCM per file and removed legacy Fernet support from the active format.
- Switched Peridot compression to prefer `zstd`, with automatic `gzip` fallback when `zstandard` is unavailable in the current Python.
- Added install metadata, packaging support, install script, license and repository hygiene files for publishing on GitHub.
