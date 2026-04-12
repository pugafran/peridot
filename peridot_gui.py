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
    # Windows-friendly: force a stable encoding for JSON output.
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
            encoding="utf-8",
            errors="replace",
            env=env,
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
        if job.result and isinstance(job.result, dict) and "progress" in job.result:
            try:
                final_result["progress"] = job.result.get("progress")
            except Exception:
                pass

        job.result = final_result
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
        # Windows-friendly path guard:
        # - Avoid naive string prefix checks (case/sep issues on Windows)
        # - Ensure the resolved asset stays within web_root
        root = web_root.resolve()
        path = (web_root / asset).resolve()
        try:
            path.relative_to(root)
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
        try:
            exe = os.environ.get("PERIDOT_EXE") or "peridot"
            p = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
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

    def _expand_path(p: str) -> str:
        # Expand ~ and environment variables, then resolve to an absolute path.
        # Use strict=False so non-existing paths still resolve sensibly.
        return str(Path(os.path.expandvars(os.path.expanduser(p))).resolve(strict=False))

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
        for p in expanded:
            pp = Path(p)
            try:
                if pp.expanduser().exists():
                    existing.append(pp)
                else:
                    missing.append(p)
            except Exception:
                missing.append(p)

        entries = peridot_mod.collect_files(existing)
        entries = peridot_mod.filter_entries(entries, excludes)
        sensitive = peridot_mod.detect_sensitive_entries(entries)

        total_bytes = int(sum(getattr(e, "size", 0) for e in entries))
        return {
            "preset": preset or None,
            "paths": paths,
            "expanded_paths": expanded,
            "missing_paths": missing,
            "excludes": excludes,
            "files": len(entries),
            "bytes": total_bytes,
            "sensitive": sorted({e.relative_path.replace("\\", "/") for e in sensitive}),
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

        - dir: optional directory to search for *.peridot (defaults to cwd).
        Also includes history snapshots from Peridot history dir.
        """

        try:
            import peridot as peridot_mod  # type: ignore

            history_dir = getattr(peridot_mod, "DEFAULT_HISTORY_DIR", None)
        except Exception:
            history_dir = None

        base = Path(dir).expanduser() if dir else Path.cwd()
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
            p = _expand_path(path)
            return _run_peridot_json(["inspect", p, "--json"])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/apply/plan")
    def apply_plan(payload: dict[str, Any]) -> Any:
        package_raw = str(payload.get("package") or "")
        target_raw = str(payload.get("target") or "")
        ignore_platform = bool(payload.get("ignore_platform") or False)
        transactional = bool(payload.get("transactional") if payload.get("transactional") is not None else True)
        verify = bool(payload.get("verify") if payload.get("verify") is not None else True)

        package = _expand_path(package_raw) if package_raw else ""
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

        package = _expand_path(package_raw) if package_raw else ""
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
        _JOBS[jid] = job
        t = threading.Thread(target=_launch_job, args=(job, args), daemon=True)
        t.start()
        return {"job_id": jid}

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
            # Initial comment to get the stream started reliably on some clients.
            yield ": ok\n\n"
            while True:
                try:
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
                except GeneratorExit:
                    # Client disconnected.
                    return

        headers = {
            # Make proxies/servers less likely to buffer SSE.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

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
