"""All-in-one runner for single-container hosts (Render, Fly.io, Railway, a bare VM).

    python -m marketdesk.serve

Starts the web server first and the alert worker (at lower CPU priority) only once the web server
answers, so on small CPU allowances (Render Free) the site becomes usable as early as possible. Both processes
validate settings and apply migrations themselves (serialised by a file lock), so there is no
separate pre-start process. If either exits (for example after passing its memory soft limit), only that process
is restarted; repeated quick web failures stop the container so the platform restarts it.
Listens on $PORT (default 8000). Standard library only.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request


def _web_ready(port: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310
            return r.status == 200
    except Exception:
        return False


def _start_worker(cmd: list[str], niceness: int, env: dict | None = None) -> subprocess.Popen:
    # Lower CPU priority: on a shared 0.1-CPU allowance page requests win over alert sampling, which
    # still gets all otherwise idle CPU time.
    def lower_priority() -> None:
        try:
            os.nice(niceness)
        except OSError:
            pass

    return subprocess.Popen(cmd, env=env, preexec_fn=lower_priority if niceness > 0 else None)  # noqa: S603, PLW1509


def _child_env() -> dict:
    env = dict(os.environ)
    env.setdefault("MALLOC_ARENA_MAX", "2")  # fewer per-thread heaps: measured -10% resident memory on the web process
    env["MARKETDESK_SUPERVISED"] = "1"  # lets each process restart itself above its memory soft limit
    return env


def main() -> int:
    port = os.environ.get("PORT", "8000")
    web_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "marketdesk.main:app",
        "--host",
        "0.0.0.0",  # noqa: S104
        "--port",
        port,
        "--proxy-headers",
        "--forwarded-allow-ips",
        os.environ.get("FORWARDED_ALLOW_IPS", "*"),
    ]
    worker_cmd = [sys.executable, "-m", "marketdesk.worker"]
    worker_nice = int(os.environ.get("WORKER_NICE", "10"))
    worker_delay = float(os.environ.get("WORKER_START_DELAY_SECONDS", "45"))
    env = _child_env()
    web = subprocess.Popen(web_cmd, env=env)  # noqa: S603
    worker: subprocess.Popen | None = None
    stopping = False

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True
        for p in (web, worker):
            if p is not None and p.poll() is None:
                p.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    # Give the web server the CPU until it answers, then start the worker.
    ready_at: float | None = None
    deadline = time.monotonic() + 600
    while not stopping and web.poll() is None and worker is None:
        if ready_at is None and _web_ready(port):
            ready_at = time.monotonic()
        if (ready_at is not None and time.monotonic() - ready_at >= worker_delay) or (
            ready_at is None and time.monotonic() > deadline
        ):
            worker = _start_worker(worker_cmd, worker_nice, env)
        time.sleep(0.5)

    # Restart only the process that exited (memory soft limit, crash); give up after repeated quick failures so the
    # platform restarts the container.
    web_restarts: list[float] = []
    worker_restarts: list[float] = []
    while not stopping:
        now = time.monotonic()
        if web.poll() is not None and not stopping:
            web_restarts = [t for t in web_restarts if now - t < 300] + [now]
            if len(web_restarts) > 5:
                stop()
                break
            print(f"marketdesk.serve: web exited ({web.returncode}); restarting", flush=True)
            web = subprocess.Popen(web_cmd, env=env)  # noqa: S603
        if worker is not None and worker.poll() is not None and not stopping:
            worker_restarts = [t for t in worker_restarts if now - t < 300] + [now]
            if len(worker_restarts) > 5:
                time.sleep(60)  # back off; alerts pause, pages keep working
                worker_restarts = []
            print(f"marketdesk.serve: worker exited ({worker.returncode}); restarting", flush=True)
            worker = _start_worker(worker_cmd, worker_nice, env)
        time.sleep(0.5)

    end = time.monotonic() + 15
    for p in (web, worker):
        if p is None:
            continue
        try:
            p.wait(timeout=max(0.1, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            p.kill()
    return 0 if stopping and len(web_restarts) <= 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
