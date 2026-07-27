from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
RUNTIME_FILE = DATA_DIR / "runtime.json"


def runtime_environment() -> dict[str, str]:
    environment = os.environ.copy()
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return environment
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not environment.get(key):
            environment[key] = value.strip().strip("\"'")
    return environment


def process_exists(process_id: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"PID eq {process_id}",
                "/FO",
                "CSV",
                "/NH",
            ],
            check=False,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return f'"{process_id}"' in result.stdout
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def hidden_flags() -> int:
    if sys.platform != "win32":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def start(port: int, open_browser: bool) -> int:
    if RUNTIME_FILE.exists():
        runtime = json.loads(RUNTIME_FILE.read_text(encoding="utf-8-sig"))
        running = [
            process_id
            for process_id in (runtime.get("api_pid"), runtime.get("worker_pid"))
            if process_id and process_exists(int(process_id))
        ]
        if running:
            print("平台已经运行，请先执行 scripts\\stop.ps1。")
            return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    api_out = (LOG_DIR / "api.out.log").open("a", encoding="utf-8")
    api_err = (LOG_DIR / "api.err.log").open("a", encoding="utf-8")
    worker_out = (LOG_DIR / "worker.out.log").open("a", encoding="utf-8")
    worker_err = (LOG_DIR / "worker.err.log").open("a", encoding="utf-8")
    creationflags = hidden_flags()
    environment = runtime_environment()

    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_DIR,
        stdout=api_out,
        stderr=api_err,
        creationflags=creationflags,
        env=environment,
    )
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.worker", "--pools", "python,http"],
        cwd=BACKEND_DIR,
        stdout=worker_out,
        stderr=worker_err,
        creationflags=creationflags,
        env=environment,
    )
    runtime = {
        "api_pid": api.pid,
        "worker_pid": worker.pid,
        "port": port,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    RUNTIME_FILE.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    health_url = f"http://127.0.0.1:{port}/api/health"
    for _ in range(40):
        if api.poll() is not None or worker.poll() is not None:
            break
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok":
                print(f"财务 Skill 平台已启动：http://127.0.0.1:{port}")
                print(f"API PID={api.pid}，Worker PID={worker.pid}")
                if open_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}")
                return 0
        except (OSError, ValueError):
            time.sleep(0.25)

    for process in (api, worker):
        if process.poll() is None:
            process.terminate()
    RUNTIME_FILE.unlink(missing_ok=True)
    print("平台启动失败，请查看 data\\logs 下的日志。", file=sys.stderr)
    return 1


def stop() -> int:
    if not RUNTIME_FILE.exists():
        print("没有发现运行中的平台实例。")
        return 0
    runtime = json.loads(RUNTIME_FILE.read_text(encoding="utf-8-sig"))
    for process_id in (runtime.get("worker_pid"), runtime.get("api_pid")):
        if not process_id:
            continue
        if process_exists(int(process_id)):
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.kill(int(process_id), 15)
            print(f"已停止 PID {process_id}。")
    RUNTIME_FILE.unlink(missing_ok=True)
    print("财务 Skill 平台已停止。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="财务 Skill 平台本地进程管理")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--port", type=int, default=8000)
    start_parser.add_argument("--no-browser", action="store_true")
    commands.add_parser("stop")
    args = parser.parse_args()
    if args.command == "start":
        return start(args.port, not args.no_browser)
    return stop()


if __name__ == "__main__":
    raise SystemExit(main())
