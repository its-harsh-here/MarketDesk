"""All-in-one runner for single-container hosts (Render, Fly.io, Railway, a bare VM).

    python -m marketdesk.serve

Starts the web server first and the alert worker (at lower CPU priority) only once the web server
answers, so on small CPU allowances (Render Free) the site becomes usable as early as possible. Both processes
validate settings and apply migrations themselves (serialised by a file lock), so there is no
separate pre-start process. If either exits, the other is stopped and the container exits
non-zero so the platform restarts it. Listens on $PORT (default 8000). Standard library only.
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


def _start_worker(cmd: list[str], niceness: int) -> subprocess.Popen:
    # Lower CPU priority: on a shared 0.1-CPU allowance page requests win over alert sampling, which
    # still gets all otherwise idle CPU time.
    def lower_priority() -> None:
        try:
            os.nice(niceness)
        except OSError:
            pass

    return subprocess.Popen(cmd, preexec_fn=lower_priority if niceness > 0 else None)  # noqa: S603, PLW1509


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
    procs: list[subprocess.Popen] = [subprocess.Popen(web_cmd)]  # noqa: S603
    web = procs[0]
    stopping = False

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True
        for p in procs:
            if p.poll() is None:
                p.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    # Give the web server the CPU until it answers, then start the worker.
    ready_at: float | None = None
    deadline = time.monotonic() + 600
    while not stopping and web.poll() is None and len(procs) == 1:
        if ready_at is None and _web_ready(port):
            ready_at = time.monotonic()
        if ready_at is not None and time.monotonic() - ready_at >= worker_delay:
            procs.append(_start_worker(worker_cmd, worker_nice))
            break
        if ready_at is None and time.monotonic() > deadline:
            procs.append(_start_worker(worker_cmd, worker_nice))  # start anyway; health is the platform's call
            break
        time.sleep(0.5)

    exit_code = 0
    while True:
        for p in procs:
            code = p.poll()
            if code is not None:
                exit_code = exit_code or code or (0 if stopping else 1)
                stop()
                end = time.monotonic() + 15
                for other in procs:
                    try:
                        other.wait(timeout=max(0.1, end - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        other.kill()
                return exit_code
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
