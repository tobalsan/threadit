import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from threaddit.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    """Real HTTP server in a thread, with its own temp DB for each test."""
    port = _free_port()
    config = uvicorn.Config(
        create_app(str(tmp_path / "e2e.db")),
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="warning",
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 20
        while not srv.started:
            if not thread.is_alive() or time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.005)
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "server thread did not stop"


@pytest.fixture
def subprocess_server(tmp_path):
    """Real `python -m threaddit` process, for the entrypoint smoke test."""
    port = _free_port()
    env = {
        **os.environ,
        "THREADDIT_DB": str(tmp_path / "e2e.db"),
        "THREADDIT_HOST": "127.0.0.1",
        "THREADDIT_PORT": str(port),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "threaddit"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 20
        while True:
            try:
                urllib.request.urlopen(base + "/", timeout=1).read()
                break
            except OSError:
                if proc.poll() is not None or time.time() > deadline:
                    raise RuntimeError("server did not start")
                time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        assert proc.poll() is not None, "server process did not stop"
