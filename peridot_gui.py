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
    try:
        job.result = _run_peridot_json(peridot_args)
        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)
    finally:
        job.finished_ts = time.time()


# --- FastAPI app ---

def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Peridot GUI (experimental)")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")

    @app.get("/api/doctor")
    def doctor() -> dict[str, Any]:
        return _run_peridot_json(["doctor", "--json"])

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        return _run_peridot_json(["settings", "--json"])

    @app.post("/api/pack")
    def pack(payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "")
        paths = payload.get("paths") or []
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise HTTPException(status_code=400, detail="paths must be a list of strings")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        out = payload.get("output")
        args = ["pack", name, *paths, "--json", "--yes"]
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
