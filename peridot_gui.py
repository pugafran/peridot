"""Experimental Peridot GUI (local web app).

Run (dev):
  python -m pip install -e ".[gui]"
  python -m peridot_gui

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


def _run_peridot_json(args: list[str]) -> dict[str, Any]:
    exe = os.environ.get("PERIDOT_EXE") or "peridot"
    cmd = [exe, *args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip() or f"peridot exited {p.returncode}")

    # JSON commands must print JSON to stdout.
    try:
        return json.loads(p.stdout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Invalid JSON output from peridot: {exc}. Output was: {p.stdout[:400]}")


def _launch_job(job: Job, peridot_args: list[str]) -> None:
    job.status = "running"
    job.started_ts = time.time()

    exe = os.environ.get("PERIDOT_EXE") or "peridot"
    cmd = [exe, *peridot_args]

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
        if progress_path:
            env["PERIDOT_PROGRESS_PATH"] = progress_path

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        stop = False

        def progress_reader():
            if not progress_path:
                return
            last_size = 0
            while not stop:
                try:
                    p = Path(progress_path)
                    if not p.exists():
                        time.sleep(0.2)
                        continue
                    data = p.read_text(encoding="utf-8", errors="replace")
                    # Only process the last line (cheap).
                    lines = [ln for ln in data.splitlines() if ln.strip()]
                    if lines:
                        try:
                            evt = json.loads(lines[-1])
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
            job.result = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Invalid JSON output from peridot: {exc}. Stdout was: {out[:400]}. Stderr was: {err[:400]}"
            )

        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
    finally:
        job.finished_ts = time.time()
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

    @app.get("/web/{asset}")
    def web_asset(asset: str):
        path = (web_root / asset).resolve()
        if not str(path).startswith(str(web_root.resolve())):
            raise HTTPException(status_code=400, detail="invalid asset")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path)

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        # Minimal metadata for the GUI.
        # Presets are static in peridot.py, so we expose them here so the UI can render cards.
        # Determine peridot version from `peridot --version` (stable, lightweight).
        try:
            exe = os.environ.get("PERIDOT_EXE") or "peridot"
            p = subprocess.run([exe, "--version"], capture_output=True, text=True)
            peridot_version = (p.stdout or "").strip() if p.returncode == 0 else None
        except Exception:
            peridot_version = None

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

        return {
            "version": peridot_version,
            "host": host,
            "language": language,
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

    def _expand_path(p: str) -> str:
        return str(Path(os.path.expandvars(os.path.expanduser(p))).resolve())

    @app.post("/api/pack/scan")
    def pack_scan(payload: dict[str, Any]) -> dict[str, Any]:
        """Scan input paths and return a summary + sensitive paths.

        This runs in-process by importing peridot, so we can surface sensitive
        warnings before creating a bundle.
        """

        preset = str(payload.get("preset") or "").strip()
        paths = payload.get("paths") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise HTTPException(status_code=400, detail="paths must be a list of strings")

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

        entries = peridot_mod.collect_files([Path(p) for p in expanded])
        entries = peridot_mod.filter_entries(entries, [])
        sensitive = peridot_mod.detect_sensitive_entries(entries)

        total_bytes = int(sum(getattr(e, "size", 0) for e in entries))
        return {
            "paths": paths,
            "expanded_paths": expanded,
            "files": len(entries),
            "bytes": total_bytes,
            "sensitive": sorted({e.relative_path.replace("\\", "/") for e in sensitive}),
        }

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
        out = payload.get("output")
        args = ["pack", name, *paths, "--json", "--yes"]
        for pat in excludes:
            args.extend(["--exclude", pat])
        if preset:
            args.extend(["--preset", preset])
        if out:
            args.extend(["--output", str(out)])

        jid = str(uuid.uuid4())
        job = Job(id=jid, kind="pack", status="queued", created_ts=time.time())
        _JOBS[jid] = job
        t = threading.Thread(target=_launch_job, args=(job, args), daemon=True)
        t.start()
        return {"job_id": jid}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
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
    def job_events(job_id: str):
        """Server-Sent Events stream for job status.

        This is a simple streaming layer (not true per-file progress yet), but it
        makes the UI feel alive.
        """

        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        def gen():
            last_status = None
            while True:
                j = _JOBS.get(job_id)
                if not j:
                    yield "event: done\ndata: {}\n\n"
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

                yield f"data: {json.dumps(payload)}\n\n"
                if j.status in {"done", "error"}:
                    return

                # basic heartbeat
                time.sleep(0.8)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def main() -> None:
    try:
        import uvicorn
    except ModuleNotFoundError:
        sys.stderr.write("Missing dependency: uvicorn. Install with: python -m pip install -e '.[gui]'\n")
        raise SystemExit(1)

    host = os.environ.get("PERIDOT_GUI_HOST", "127.0.0.1")
    port = int(os.environ.get("PERIDOT_GUI_PORT", "8844"))
    uvicorn.run("peridot_gui:create_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
