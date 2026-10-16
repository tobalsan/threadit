import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
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
