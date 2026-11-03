"""All-in-one runner for single-container hosts (Render, Fly.io, Railway, a bare VM).

    python -m marketdesk.serve

Applies migrations once, then supervises exactly one web server and one alert worker in the
same container so both share the SQLite file on the attached disk. If either process exits, the
other is stopped and the container exits non-zero so the platform restarts it. Listens on $PORT
(default 8000). Docker Compose does not need this: it runs migrate, web and worker as services.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def main() -> int:
    # Validate configuration and apply migrations in a short-lived process, so this supervisor
    # stays small (standard library only) for the lifetime of the container.
    pre = subprocess.run([sys.executable, "-m", "marketdesk.cli", "preflight"], check=False)  # noqa: S603
    if pre.returncode != 0:
        return pre.returncode
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
    procs = [subprocess.Popen(worker_cmd), subprocess.Popen(web_cmd)]  # noqa: S603

    stopping = False

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True
        for p in procs:
            if p.poll() is None:
                p.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    exit_code = 0
    while True:
        for p in procs:
            code = p.poll()
            if code is not None:
                exit_code = exit_code or code or (0 if stopping else 1)
                stop()
                deadline = time.monotonic() + 15
                for other in procs:
                    remaining = max(0.1, deadline - time.monotonic())
                    try:
                        other.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        other.kill()
                return exit_code
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
