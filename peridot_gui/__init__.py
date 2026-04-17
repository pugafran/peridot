"""Experimental Peridot GUI (local web app).

Run (dev):
  python -m pip install -e ".[gui]"
  python -m peridot_gui

Run (installed):
  peridot-gui

This is intentionally an *experimental* module so we can iterate without
locking the CLI into a heavy GUI stack.

The GUI talks to Peridot via subprocess calls to the installed `peridot`
command in JSON mode.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# FastAPI treats `Request` specially only when its type can be resolved from the
# function globals. Because this module uses `from __future__ import
# annotations`, FastAPI relies on evaluating annotations at runtime. If we only
# import Request inside create_app(), it won't be available in globals and FastAPI
# will incorrectly interpret it as a query parameter.
try:  # pragma: no cover (depends on optional GUI deps)
    from starlette.requests import Request as StarletteRequest
except Exception:  # pragma: no cover
    StarletteRequest = Any  # type: ignore


@dataclass
class Job:
    id: str
    kind: str
    status: str  # queued|running|done|error
    created_ts: float
    started_ts: float | None = None
    finished_ts: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def _prune_jobs(*, keep: int = 50, min_age_seconds: float = 3600.0) -> None:
    """Best-effort pruning of completed jobs.

    The experimental GUI is designed to be left open while iterating. Without
    pruning, a long session can accumulate lots of finished jobs in memory.

    We keep this logic intentionally simple (Windows-first, no background
    schedulers): prune opportunistically when jobs finish.
    """

    try:
        now = time.time()
        with _JOBS_LOCK:
            items = list(_JOBS.values())
            # Keep running/queued jobs regardless of age.
            done = [j for j in items if j.status in {"done", "error"} and (j.finished_ts or 0) > 0]
            done.sort(key=lambda j: (j.finished_ts or 0))

            # Only prune if we have more than `keep` completed jobs.
            extra = max(0, len(done) - keep)
            if extra <= 0:
                return

            # Prune oldest completed jobs, but only if they are old enough.
            prunable = [j for j in done[:extra] if (now - float(j.finished_ts or now)) >= min_age_seconds]
            for j in prunable:
                _JOBS.pop(j.id, None)
    except Exception:
        return


def _peridot_cmd_prefix() -> list[str]:
    """Return the command prefix used to invoke the Peridot CLI.

    Supports:
    - PERIDOT_EXE="peridot" (default)
    - PERIDOT_EXE="C:\\Path With Spaces\\peridot.exe"
    - PERIDOT_EXE="python -m peridot" (useful for dev/tests)

    Windows-first behavior:
    - If PERIDOT_EXE is not set and `peridot` is not on PATH, we fall back to
      invoking the module via the current interpreter: `python -m peridot`.

    We avoid shell=True for safety and Windows consistency.
    """

    import importlib.util
    import shlex
    import shutil

    raw_env = os.environ.get("PERIDOT_EXE")
    raw = (raw_env or "peridot").strip() or "peridot"

    # If the user didn't override PERIDOT_EXE and there is no `peridot`
    # executable on PATH (common on fresh Windows installs / editable dev
    # checkouts), use `python -m peridot`.
    if raw_env is None and raw == "peridot" and shutil.which("peridot") is None:
        if importlib.util.find_spec("peridot") is not None:
            return [sys.executable, "-m", "peridot"]

    # shlex on Windows uses different quoting rules; best-effort.
    try:
        parts = shlex.split(raw, posix=(os.name != "nt"))
    except Exception:
        parts = [raw]

    return parts or ["peridot"]


def _run_peridot_json(args: list[str]) -> dict[str, Any]:
    cmd = [*_peridot_cmd_prefix(), *args]

    # Windows-first: prevent console windows from flashing when the GUI spawns
    # subprocesses (best-effort; no-op on non-Windows).
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # Windows-friendly: enforce UTF-8 for any Python-based Peridot CLI.
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # Safety (Windows-first): a hung subprocess would freeze the GUI endpoint.
    # Keep a configurable timeout with a conservative default.
    try:
        timeout_s = float(os.environ.get("PERIDOT_GUI_CLI_TIMEOUT", "60"))
    except Exception:
        timeout_s = 60.0

    # Windows-friendly: force a stable encoding for JSON output.
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"peridot command timed out after {timeout_s:.0f}s: {cmd}") from exc
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"peridot exited {p.returncode}")

    # JSON commands must print JSON to stdout.
    try:
        return json.loads(p.stdout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid JSON output from peridot: {exc}. Output was: {p.stdout[:400]}")


def _expand_path(p: str) -> str:
    """Expand a user-supplied path into an absolute, normalized path.

    Windows-first behavior:
    - Accepts ~ and environment variables.
    - Avoids Path.resolve() edge-cases on Windows (e.g. drive-relative paths,
      non-existent drives, weird prefixes) by falling back to abspath.
    """

    raw = str(p or "")
    expanded = os.path.expandvars(os.path.expanduser(raw))

    # Normalize separators a bit for display/consistency; the OS APIs can still
    # accept forward slashes on Windows, but we prefer native.
    if os.name == "nt":
        expanded = expanded.replace("/", "\\")

    try:
        return str(Path(expanded).resolve(strict=False))
    except Exception:
        # Last resort: avoid raising on odd Windows paths.
        return os.path.abspath(expanded)


def _default_output_dir() -> Path:
    """Pick a sensible default output directory.

    Usability note (Windows-first): when the GUI is launched from a shortcut /
    Start Menu, the process cwd can be something like System32, which is a
    terrible default for writing files.

    We prefer:
    - ~/Downloads if it exists
    - else the user's home directory
    - else the current working directory
    """

    try:
        home = Path.home()
        dl = home / "Downloads"
        if dl.exists() and dl.is_dir():
            return dl
        if home.exists() and home.is_dir():
            return home
    except Exception:
        pass
    return Path.cwd()


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in ("-", "_", "."):
            out.append(ch)
        elif ch.isspace():
            out.append("-")
    slug = "".join(out).strip("-._")
    return slug or "bundle"


def _compute_output_path(*, name: str, output_raw: str | None) -> str:
    """Compute a safe output bundle path.

    Windows-first UX:
    - If the user doesn't provide an output path, write into a sensible default
      directory (usually ~/Downloads).
    - If the user provides only a filename (relative, no directory component),
      also write into the default directory.
      (Important on Windows: GUI apps launched via shortcuts often start in
      System32, and writing there is confusing / may fail.)
    - If the user passes a directory (existing) or a path ending in a path
      separator (e.g. "C:\\tmp\\"), write into that directory using a
      deterministic filename.
    - Otherwise treat it as a file path.
    """

    suggested_name = f"{_slug(name)}.peridot"

    if not output_raw:
        return str((_default_output_dir() / suggested_name))

    raw = str(output_raw).strip()
    if not raw:
        return str((_default_output_dir() / suggested_name))

    # If the UI provides a simple filename (our default), treat it as living in
    # the default output directory.
    raw_name = None
    try:
        raw_p = Path(raw)
        raw_name = raw_p.name
        is_simple_name = (raw_p.name == raw) and (str(raw_p.parent) in {".", ""})
    except Exception:
        is_simple_name = False

    if is_simple_name and raw_name:
        return str((_default_output_dir() / raw_name))

    expanded = _expand_path(raw)
    p = Path(expanded)

    if raw.endswith(("/", "\\")):
        return str((p / suggested_name))

    try:
        if p.exists() and p.is_dir():
            return str((p / suggested_name))
    except Exception:
        pass

    return str(p)


def _resolve_bundle_path(raw: str) -> str:
    """Resolve a user-supplied bundle path for GUI endpoints.

    Windows-first UX: if the user types only a filename (no directory), resolve
    it against the GUI default output directory instead of the current working
    directory (which may be System32 when launched via a shortcut).
    """

    s = str(raw or "").strip()
    if not s:
        return ""

    try:
        p = Path(s)
        is_simple_name = (p.name == s) and (str(p.parent) in {".", ""})
    except Exception:
        is_simple_name = False

    if is_simple_name:
        return str((_default_output_dir() / s))

    return _expand_path(s)


def _launch_job(job: Job, peridot_args: list[str]) -> None:
    # Jobs are mutated from background threads while the API is serving status
    # and SSE events. Keep updates under a lock so we don't expose partially
    # updated state (Windows-first: helps avoid flaky UI behavior under load).
    with _JOBS_LOCK:
        job.status = "running"
        job.started_ts = time.time()

    cmd = [*_peridot_cmd_prefix(), *peridot_args]

    # Cross-platform progress stream via a temp JSONL file.
    progress_path = None
    try:
        import tempfile

        progress_fd, progress_path = tempfile.mkstemp(prefix="peridot-progress-", suffix=".jsonl")
        os.close(progress_fd)
    except Exception:
        progress_path = None

    try:
        env = dict(os.environ)
        # Ensure consistent encoding when the CLI is `python -m peridot`.
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if progress_path:
            env["PERIDOT_PROGRESS_PATH"] = progress_path

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )

        stop = False

        def progress_reader():
            """Read the latest JSONL progress event.

            Keep it lightweight (tail-read) so it behaves well on Windows too.
            """

            if not progress_path:
                return

            while not stop:
                try:
                    p = Path(progress_path)
                    if not p.exists():
                        time.sleep(0.2)
                        continue

                    # Tail-read ~8KiB and parse the last non-empty line.
                    try:
                        with p.open("rb") as f:
                            f.seek(0, os.SEEK_END)
                            size = f.tell()
                            f.seek(max(0, size - 8192), os.SEEK_SET)
                            chunk = f.read()
                        data = chunk.decode("utf-8", errors="replace")
                    except Exception:
                        # Fallback for unusual filesystems.
                        data = p.read_text(encoding="utf-8", errors="replace")

                    lines = [ln for ln in data.splitlines() if ln.strip()]
                    if lines:
                        try:
                            evt = json.loads(lines[-1])
                            with _JOBS_LOCK:
                                job.result = job.result or {}
                                job.result["progress"] = evt
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(0.35)

        t = threading.Thread(target=progress_reader, daemon=True)
        t.start()

        out, err = proc.communicate()
        stop = True

        if proc.returncode != 0:
            raise RuntimeError((err or out or "").strip() or f"peridot exited {proc.returncode}")

        try:
            final_result = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Invalid JSON output from peridot: {exc}. Stdout was: {out[:400]}. Stderr was: {err[:400]}"
            )

        # Preserve any last progress event we captured via PERIDOT_PROGRESS_PATH.
        try:
            with _JOBS_LOCK:
                latest_progress = None
                if job.result and isinstance(job.result, dict) and "progress" in job.result:
                    latest_progress = job.result.get("progress")
            if latest_progress is not None:
                final_result["progress"] = latest_progress
        except Exception:
            pass

        # UX: when packing, show bundle size without the UI needing to stat paths.
        # Windows-first: always use pathlib for robust path handling.
        try:
            out_path = final_result.get("output") if isinstance(final_result, dict) else None
            if out_path:
                p_out = Path(str(out_path))
                if p_out.exists() and p_out.is_file():
                    final_result.setdefault("output_bytes", p_out.stat().st_size)
        except Exception:
            pass

        with _JOBS_LOCK:
            job.result = final_result
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        with _JOBS_LOCK:
            job.status = "error"
            job.error = str(exc)
    finally:
        with _JOBS_LOCK:
            job.finished_ts = time.time()
        # Opportunistic cleanup to keep long-running GUI sessions stable.
        _prune_jobs()
        if progress_path:
            try:
                Path(progress_path).unlink(missing_ok=True)
            except Exception:
                pass


# --- FastAPI app ---

def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

    app = FastAPI(title="Peridot GUI (experimental)")

    web_root = Path(__file__).parent / "web"

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (web_root / "index.html").read_text(encoding="utf-8")

    @app.get("/web/{asset:path}")
    def web_asset(asset: str):
        # Windows-first path guard:
        # - Avoid naive string prefix checks (case/sep issues on Windows)
        # - Ensure the resolved asset stays within web_root
        root = web_root.resolve()
        path = (web_root / asset).resolve()

        # pathlib.Path.relative_to() is strict about casing on some platforms.
        # Use a normcased commonpath check to behave reliably on Windows.
        import os as _os

        root_s = _os.path.normcase(str(root))
        path_s = _os.path.normcase(str(path))
        try:
            if _os.path.commonpath([path_s, root_s]) != root_s:
                raise HTTPException(status_code=400, detail="invalid asset")
        except Exception:
            raise HTTPException(status_code=400, detail="invalid asset")

        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path)

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        # Minimal metadata for the GUI.
        # Presets are static in peridot.py, so we expose them here so the UI can render cards.
        # Determine peridot version from `peridot --version` (stable, lightweight).
        peridot_cmd = _peridot_cmd_prefix()
        peridot_version = None
        peridot_version_error = None
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            env = dict(os.environ)
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                timeout_s = float(os.environ.get("PERIDOT_GUI_CLI_TIMEOUT", "10"))
            except Exception:
                timeout_s = 10.0

            p = subprocess.run(
                [*peridot_cmd, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
                timeout=timeout_s,
            )
            peridot_version = (p.stdout or "").strip() if p.returncode == 0 else None
            if p.returncode != 0:
                peridot_version_error = (p.stderr or p.stdout or "").strip() or f"exit {p.returncode}"
        except Exception as exc:  # noqa: BLE001
            peridot_version_error = str(exc)

        host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""
        language = None
        try:
            import peridot as peridot_mod  # type: ignore

            try:
                language = (peridot_mod.load_settings() or {}).get("language")
            except Exception:
                language = None

            presets = []
            for k, v in getattr(peridot_mod, "PRESET_LIBRARY", {}).items():
                presets.append(
                    {
                        "key": k,
                        "description": v.get("description"),
                        "platform": v.get("platform"),
                        "shell": v.get("shell"),
                        "tags": v.get("tags"),
                        "paths": v.get("paths"),
                    }
                )
        except Exception:
            presets = []

        gui_host = os.environ.get("PERIDOT_GUI_HOST", "127.0.0.1")
        try:
            gui_port = int(os.environ.get("PERIDOT_GUI_PORT", "8844"))
        except Exception:
            gui_port = 8844

        return {
            "version": peridot_version,
            "version_error": peridot_version_error,
            "peridot_cmd": peridot_cmd,
            "host": host,
            "language": language,
            "gui": {
                "host": gui_host,
                "port": gui_port,
                "base_url": f"http://{gui_host}:{gui_port}",
            },
            # Usability (Windows-first): a safe default output directory so the
            # UI can explain where bundles will land when the user provides only
            # a filename.
            "default_output_dir": str(_default_output_dir()),
            "runtime": {
                "os_name": os.name,
                "sys_platform": sys.platform,
                "arch": os.environ.get("PROCESSOR_ARCHITECTURE") or os.environ.get("HOSTTYPE") or "",
                "cwd": str(Path.cwd()),
            },
            "presets": sorted(presets, key=lambda p: p.get("key") or ""),
        }

    @app.get("/api/doctor")
    def doctor() -> Any:
        try:
            return _run_peridot_json(["doctor", "--json"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/settings")
    def settings() -> Any:
        # Prefer in-process access (works even if the installed CLI doesn't yet
        # support `settings --json`).
        try:
            import peridot as peridot_mod  # type: ignore

            settings_path = str(getattr(peridot_mod, "DEFAULT_SETTINGS_STORE"))
            data = peridot_mod.load_settings()
            return {"settings_path": settings_path, "settings": data}
        except SystemExit as exc:
            raise HTTPException(status_code=500, detail=f"peridot load_settings failed: {exc}")
        except Exception:
            # Fallback to CLI if import fails.
            try:
                return _run_peridot_json(["settings", "--json"])
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

    # _expand_path is defined at module scope for testability.

    @app.post("/api/pack/scan")
    def pack_scan(payload: dict[str, Any]) -> dict[str, Any]:
        """Scan input paths and return a summary + sensitive paths.

        This runs in-process by importing peridot, so we can surface sensitive
        warnings before creating a bundle.

        Accepts optional `excludes` patterns (same semantics as CLI `--exclude`).
        """

        preset = str(payload.get("preset") or "").strip()
        paths = payload.get("paths") or []
        excludes = payload.get("excludes") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise HTTPException(status_code=400, detail="paths must be a list of strings")
        if not isinstance(excludes, list) or not all(isinstance(p, str) for p in excludes):
            raise HTTPException(status_code=400, detail="excludes must be a list of strings")

        try:
            import peridot as peridot_mod  # type: ignore
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"cannot import peridot: {exc}")

        # If preset is provided, use its default paths when no paths are supplied.
        if preset and not paths:
            spec = getattr(peridot_mod, "PRESET_LIBRARY", {}).get(preset)
            if not spec:
                raise HTTPException(status_code=400, detail=f"unknown preset: {preset}")
            paths = list(spec.get("paths") or [])

        expanded = [_expand_path(p) for p in paths]

        # Windows-first UX: presets may include paths that don't exist on a given
        # machine (e.g. fresh installs). Avoid noisy console prints from
        # collect_files() and surface missing paths explicitly to the UI.
        existing: list[Path] = []
        missing: list[str] = []
        skipped: list[str] = []
        for p in expanded:
            pp = Path(p)
            try:
                ex = pp.expanduser()
                if not ex.exists():
                    missing.append(p)
                    continue
                # Keep GUI scan stable: skip symlinks (Peridot will skip them
                # anyway, but may print a warning).
                if ex.is_symlink():
                    skipped.append(p)
                    continue
                existing.append(ex)
            except Exception:
                missing.append(p)

        # Avoid noisy console output from peridot (e.g. warnings about skipped
        # paths) when scanning via the GUI.
        try:
            from contextlib import contextmanager

            @contextmanager
            def _silence_console():
                original = getattr(peridot_mod, "console", None)
                try:
                    peridot_mod.console = type("_NullConsole", (), {"print": lambda *_a, **_k: None})()  # type: ignore[attr-defined]
                    yield
                finally:
                    if original is not None:
                        peridot_mod.console = original  # type: ignore[attr-defined]

            with _silence_console():
                entries = peridot_mod.collect_files(existing)
        except Exception:
            entries = peridot_mod.collect_files(existing)

        entries = peridot_mod.filter_entries(entries, excludes)
        sensitive_entries = peridot_mod.detect_sensitive_entries(entries)

        def _sensitive_reason(relpath: str) -> str:
            rp = (relpath or "").replace("\\", "/")
            name = rp.split("/")[-1].lower()
            rp_l = rp.lower()

            if name in {".env", ".env.local", ".env.production", ".env.development", ".env.test"} or "/.env" in rp_l:
                return "Environment file (.env)"
            if name == ".netrc" or rp_l.endswith("/.netrc"):
                return "netrc credentials"
            if "/.ssh/" in rp_l or rp_l.startswith(".ssh/"):
                if name.startswith("id_") and not name.endswith(".pub"):
                    return "SSH private key"
                if "known_hosts" in name or name == "config":
                    return "SSH configuration"
                return "SSH-related file"
            if "credential" in name or "/credentials" in rp_l or "credentials" in name:
                return "Credentials file"
            if "token" in name or "/token" in rp_l:
                return "Token file"

            return "Sensitive path detected"

        sensitive_paths = sorted({e.relative_path.replace("\\", "/") for e in sensitive_entries})
        sensitive = [{"path": p, "reason": _sensitive_reason(p)} for p in sensitive_paths]

        total_bytes = int(sum(getattr(e, "size", 0) for e in entries))
        return {
            "preset": preset or None,
            "paths": paths,
            "expanded_paths": expanded,
            # Paths that actually contributed to the scan (exist + not symlink).
            "existing_paths": [str(p) for p in existing],
            "missing_paths": missing,
            "skipped_paths": skipped,
            "excludes": excludes,
            "files": len(entries),
            "bytes": total_bytes,
            # Back-compat: keep sensitive_paths as a simple list.
            "sensitive_paths": sensitive_paths,
            # Preferred shape for the GUI.
            "sensitive": sensitive,
        }

    def _list_bundles_in_dir(dir_path: Path) -> list[dict[str, Any]]:
        if not dir_path.exists() or not dir_path.is_dir():
            return []
        out = []
        for p in sorted(dir_path.glob("*.peridot")):
            try:
                out.append({"path": str(p), "name": p.name, "bytes": p.stat().st_size, "source": "dir"})
            except Exception:
                out.append({"path": str(p), "name": p.name, "bytes": None, "source": "dir"})
        return out

    @app.get("/api/bundles")
    def bundles(dir: str | None = None) -> dict[str, Any]:
        """List local bundles.

        - dir: optional directory to search for *.peridot.
          Defaults to the GUI default output directory (usually ~/Downloads) to
          avoid surprising empty lists when the GUI is launched with cwd=System32
          on Windows.
        Also includes history snapshots from Peridot history dir.
        """

        try:
            import peridot as peridot_mod  # type: ignore

            history_dir = getattr(peridot_mod, "DEFAULT_HISTORY_DIR", None)
        except Exception:
            history_dir = None

        base = Path(dir).expanduser() if dir else _default_output_dir()
        items = _list_bundles_in_dir(base)

        history_items: list[dict[str, Any]] = []
        if history_dir:
            try:
                for p in sorted(Path(history_dir).glob("**/*.peridot")):
                    history_items.append({"path": str(p), "name": p.name, "bytes": p.stat().st_size, "source": "history"})
            except Exception:
                history_items = []

        return {"dir": str(base), "items": items, "history": history_items}

    @app.get("/api/inspect")
    def inspect_bundle(path: str) -> Any:
        # Prefer CLI JSON.
        try:
            p = _resolve_bundle_path(path)
            if not p:
                raise HTTPException(status_code=400, detail="path is required")
            return _run_peridot_json(["inspect", p, "--json"])
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/apply/plan")
    def apply_plan(payload: dict[str, Any]) -> Any:
        package_raw = str(payload.get("package") or "")
        target_raw = str(payload.get("target") or "")
        ignore_platform = bool(payload.get("ignore_platform") or False)
        transactional = bool(payload.get("transactional") if payload.get("transactional") is not None else True)
        verify = bool(payload.get("verify") if payload.get("verify") is not None else True)

        package = _resolve_bundle_path(package_raw) if package_raw else ""
        target = _expand_path(target_raw) if target_raw else ""

        if not package:
            raise HTTPException(status_code=400, detail="package is required")
        args = ["apply", package, "--dry-run", "--json"]
        if target:
            args.extend(["--target", target])
        if ignore_platform:
            args.append("--ignore-platform")
        if not transactional:
            args.append("--no-transactional")
        if not verify:
            args.append("--no-verify")
        return _run_peridot_json(args)

    def _open_path(target: Path) -> None:
        # Best-effort cross-platform open.
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
            return
        subprocess.Popen(["xdg-open", str(target)])

    def _reveal_path(target: Path) -> None:
        # Best-effort cross-platform reveal in file manager.
        if os.name == "nt":
            # Explorer can highlight a file with /select.
            t = target
            try:
                if t.exists() and t.is_file():
                    # Explorer supports: explorer.exe /select, C:\path\file
                    # When using subprocess with a list of args, avoid embedding
                    # extra quotes in the argument (Explorer can misparse it).
                    subprocess.Popen(["explorer.exe", "/select,", str(t)])
                else:
                    subprocess.Popen(["explorer.exe", str(t if t.is_dir() else t.parent)])
            except Exception:
                os.startfile(str(t if t.is_dir() else t.parent))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            # Finder: reveal file/dir
            subprocess.Popen(["open", "-R", str(target)])
            return
        subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])

    @app.post("/api/os/open")
    def os_open(payload: dict[str, Any]) -> dict[str, Any]:
        path = str(payload.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        p = Path(_expand_path(path))
        _open_path(p)
        return {"ok": True}

    @app.post("/api/os/reveal")
    def os_reveal(payload: dict[str, Any]) -> dict[str, Any]:
        path = str(payload.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        p = Path(_expand_path(path))
        _reveal_path(p)
        return {"ok": True}

    @app.post("/api/apply/run")
    def apply_run(payload: dict[str, Any]) -> dict[str, Any]:
        package_raw = str(payload.get("package") or "")
        target_raw = str(payload.get("target") or "")
        apply_token = str(payload.get("apply_token") or "")
        ignore_platform = bool(payload.get("ignore_platform") or False)
        transactional = bool(payload.get("transactional") if payload.get("transactional") is not None else True)
        verify = bool(payload.get("verify") if payload.get("verify") is not None else True)

        package = _resolve_bundle_path(package_raw) if package_raw else ""
        target = _expand_path(target_raw) if target_raw else ""

        if not package:
            raise HTTPException(status_code=400, detail="package is required")
        if not apply_token:
            raise HTTPException(status_code=400, detail="apply_token is required")

        args = ["apply", package, "--json", "--yes", "--apply-token", apply_token]
        if target:
            args.extend(["--target", target])
        if ignore_platform:
            args.append("--ignore-platform")
        if not transactional:
            args.append("--no-transactional")
        if not verify:
            args.append("--no-verify")

        jid = str(uuid.uuid4())
        job = Job(id=jid, kind="apply", status="queued", created_ts=time.time())
        with _JOBS_LOCK:
            _JOBS[jid] = job
        t = threading.Thread(target=_launch_job, args=(job, args), daemon=True)
        t.start()
        return {"job_id": jid}

    # _slug / _default_output_dir / _compute_output_path are defined at module
    # scope for testability.

    @app.post("/api/pack")
    def pack(payload: dict[str, Any]) -> dict[str, Any]:
        preset = str(payload.get("preset") or "").strip()
        name = str(payload.get("name") or "")
        paths = payload.get("paths") or []
        excludes = payload.get("excludes") or []

        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise HTTPException(status_code=400, detail="paths must be a list of strings")
        if not isinstance(excludes, list) or not all(isinstance(p, str) for p in excludes):
            raise HTTPException(status_code=400, detail="excludes must be a list of strings")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        # If preset is provided, pass it through and let peridot resolve defaults.
        # Safety: if the UI sends neither paths nor preset, Peridot CLI will
        # attempt interactive prompts (which will crash in GUI subprocesses).
        # Windows note: some environments still report stdin as a tty; to avoid
        # CLI falling into interactive prompts, we always pass --output and a
        # non-empty --description.
        out = payload.get("output")
        output_path = _compute_output_path(name=name, output_raw=(str(out) if out is not None else None))

        # NOTE: Peridot's argparse wiring is sensitive to the order of
        # positionals vs optionals for `pack`.
        #
        # `paths` must appear *immediately after* the bundle name, otherwise
        # some invocations fail with:
        #   peridot: error: unrecognized arguments: <path>
        #
        # This is especially important for the GUI where we always pass a few
        # flags.

        # Windows-first: expand user/env vars early so the CLI receives
        # absolute paths (tilde isn't native on Windows).
        expanded_paths = [_expand_path(p) for p in paths] if paths else []

        args = ["pack", name]
        if expanded_paths:
            args.extend(expanded_paths)
        elif not preset:
            raise HTTPException(status_code=400, detail="preset is required when no paths are provided")

        args.extend(["--json", "--yes", "--output", output_path, "--description", "peridot gui"])

        for pat in excludes:
            args.extend(["--exclude", pat])
        if preset:
            args.extend(["--preset", preset])

        jid = str(uuid.uuid4())
        job = Job(id=jid, kind="pack", status="queued", created_ts=time.time())
        with _JOBS_LOCK:
            _JOBS[jid] = job
        t = threading.Thread(target=_launch_job, args=(job, args), daemon=True)
        t.start()
        # UX: return the resolved output path immediately so the UI can show the
        # user where the bundle will land (important on Windows where cwd can be
        # unexpected).
        return {"job_id": jid, "output_path": output_path}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "created_ts": job.created_ts,
            "started_ts": job.started_ts,
            "finished_ts": job.finished_ts,
            "result": job.result,
            "error": job.error,
        }

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: StarletteRequest):
        """Server-Sent Events stream for job status.

        This is a simple streaming layer (not true per-file progress yet), but it
        makes the UI feel alive.

        Implemented as an async generator so we don't block the event loop
        (important for responsiveness, especially on Windows).

        We also stop streaming promptly when the client disconnects; otherwise
        some Windows browser/proxy setups can leave the server-side generator
        running longer than needed.
        """

        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        import asyncio

        async def gen():
            # Initial comment to get the stream started reliably on some clients.
            yield b": ok\n\n"
            # Hint to the browser how quickly to retry.
            yield b"retry: 1000\n\n"
            while True:
                try:
                    if await request.is_disconnected():
                        return
                except Exception:
                    # best-effort: if we can't detect disconnect, keep streaming
                    pass

                with _JOBS_LOCK:
                    j = _JOBS.get(job_id)
                if not j:
                    yield b"event: done\ndata: {}\n\n"
                    return

                payload = {
                    "id": j.id,
                    "kind": j.kind,
                    "status": j.status,
                    "created_ts": j.created_ts,
                    "started_ts": j.started_ts,
                    "finished_ts": j.finished_ts,
                    "result": j.result,
                    "error": j.error,
                }

                # EventSource default handler uses the implicit "message" event.
                yield (f"data: {json.dumps(payload, ensure_ascii=False)}\n\n").encode("utf-8")
                if j.status in {"done", "error"}:
                    return

                # basic heartbeat
                await asyncio.sleep(0.8)

        headers = {
            # Make proxies/servers less likely to buffer SSE.
            # - no-transform helps some middleware avoid compressing/buffering.
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
            # Windows-first: some setups are picky about a charset parameter.
            # We emit UTF-8 bytes, so advertise it explicitly.
            "Content-Type": "text/event-stream; charset=utf-8",
        }
        # EventSource expects exactly `text/event-stream` semantics.
        # Keep encoding UTF-8 by emitting bytes.
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    return app


def main() -> None:
    # Friendly dependency errors (Windows-first): without these, the user gets a
    # long traceback on first run.
    missing = None
    try:
        import fastapi  # noqa: F401
    except ModuleNotFoundError as exc:
        missing = exc.name or "fastapi"

    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        missing = missing or (exc.name or "uvicorn")

    if missing:
        sys.stderr.write(
            "Missing dependency: "
            + str(missing)
            + ". Install with: python -m pip install -e '.[gui]'\n"
        )
        raise SystemExit(1)

    host = os.environ.get("PERIDOT_GUI_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PERIDOT_GUI_PORT", "8844"))
    except Exception:
        port = 8844
    uvicorn.run("peridot_gui:create_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
