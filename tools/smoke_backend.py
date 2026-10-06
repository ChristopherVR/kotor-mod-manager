"""Check that the packaged sidecar starts and serves its API without Python."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="kotor-sidecar-check-") as temp:
        env = os.environ.copy()
        # Isolate config and credentials from a developer's real installation.
        env["USERPROFILE"] = temp
        env["HOME"] = temp
        with open(Path(temp) / "backend.log", "w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(executable), "--port", str(port)], env=env,
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Packaged backend exited with {process.returncode}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as response:
                            status = json.load(response)
                        assert status.get("version"), status
                        with urlopen(f"http://127.0.0.1:{port}/api/builds", timeout=2) as response:
                            assert json.load(response).get("builds")
                        print(f"Packaged backend OK (v{status['version']})")
                        return
                    except URLError:
                        time.sleep(0.25)
                raise RuntimeError("Packaged backend did not become ready within 90 seconds")
            except Exception:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                if os.name == "nt" and process.poll() is None:
                    # PyInstaller's one-file bootloader starts a child process.
                    # Stop the whole owned tree before cleaning up its log/config.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=False)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
