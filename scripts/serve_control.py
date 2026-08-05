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


def parse_worker_counts(value: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for item in value.split(","):
        pool, separator, count = item.strip().partition(":")
        if not separator or not pool:
            continue
        try:
            parsed = int(count)
        except ValueError:
            continue
        if parsed > 0:
            result.append((pool, parsed))
    return result


def worker_specs(environment: dict[str, str]) -> list[tuple[str, str]]:
    configured = environment.get(
        "FINANCIAL_WORKER_COUNTS",
        "python:2,http:2,workflow:2",
    )
    counts = parse_worker_counts(configured)
    if not counts:
        raise ValueError("FINANCIAL_WORKER_COUNTS 没有包含有效的 Worker 数量。")
    return [
        (pool, f"{pool}-{index}")
        for pool, count in counts
        for index in range(1, count + 1)
    ]


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


def process_command_line(process_id: int) -> str:
    if not process_exists(process_id):
        return ""
    if sys.platform == "win32":
        command = (
            f"$item = Get-CimInstance Win32_Process -Filter 'ProcessId = {process_id}'; "
            "if ($item) { [Console]::Out.Write($item.CommandLine) }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip()
    result = subprocess.run(
        ["ps", "-p", str(process_id), "-o", "args="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def process_matches(process_id: int, *needles: str) -> bool:
    command_line = process_command_line(process_id).lower()
    return bool(command_line) and all(needle.lower() in command_line for needle in needles)


def runtime_processes(runtime: dict[str, object]) -> list[tuple[int, tuple[str, ...]]]:
    processes: list[tuple[int, tuple[str, ...]]] = []
    workers = runtime.get("workers", [])
    if isinstance(workers, list):
        for item in workers:
            if not isinstance(item, dict) or not item.get("pid"):
                continue
            worker_id = str(item.get("worker_id", ""))
            hints = ("-m app.worker",)
            if worker_id:
                hints += ("--worker-id", worker_id)
            processes.append((int(item["pid"]), hints))
    legacy_worker = runtime.get("worker_pid")
    if legacy_worker:
        processes.append((int(legacy_worker), ("-m app.worker",)))
    api_pid = runtime.get("api_pid")
    if api_pid:
        processes.append((int(api_pid), ("uvicorn", "app.main:app")))
    return processes


def hidden_flags() -> int:
    if sys.platform != "win32":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def start(port: int, host: str, open_browser: bool) -> int:
    if RUNTIME_FILE.exists():
        runtime = json.loads(RUNTIME_FILE.read_text(encoding="utf-8-sig"))
        running = [
            process_id
            for process_id, hints in runtime_processes(runtime)
            if process_matches(process_id, *hints)
        ]
        if running:
            print("平台已经运行，请先执行 scripts\\stop.ps1。")
            return 1
        RUNTIME_FILE.unlink(missing_ok=True)
        print("已清理过期的平台运行记录。")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    api_out = (LOG_DIR / "api.out.log").open("a", encoding="utf-8")
    api_err = (LOG_DIR / "api.err.log").open("a", encoding="utf-8")
    creationflags = hidden_flags()
    environment = runtime_environment()
    specs = worker_specs(environment)

    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=BACKEND_DIR,
        stdout=api_out,
        stderr=api_err,
        creationflags=creationflags,
        env=environment,
    )
    health_url = f"http://127.0.0.1:{port}/api/health"
    api_ready = False
    for _ in range(40):
        if api.poll() is not None:
            break
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok":
                api_ready = True
                break
        except (OSError, ValueError):
            time.sleep(0.25)
    if not api_ready:
        if api.poll() is None:
            api.terminate()
        print("API 启动失败，请查看 data\\logs 下的日志。", file=sys.stderr)
        return 1

    workers: list[tuple[str, str, subprocess.Popen[bytes]]] = []
    for pool, worker_id in specs:
        worker_out = (LOG_DIR / f"worker-{worker_id}.out.log").open(
            "a", encoding="utf-8"
        )
        worker_err = (LOG_DIR / f"worker-{worker_id}.err.log").open(
            "a", encoding="utf-8"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.worker",
                "--pools",
                pool,
                "--worker-id",
                worker_id,
            ],
            cwd=BACKEND_DIR,
            stdout=worker_out,
            stderr=worker_err,
            creationflags=creationflags,
            env=environment,
        )
        workers.append((pool, worker_id, process))
    runtime = {
        "api_pid": api.pid,
        "workers": [
            {"pid": process.pid, "pool": pool, "worker_id": worker_id}
            for pool, worker_id, process in workers
        ],
        "port": port,
        "host": host,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    RUNTIME_FILE.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for _ in range(20):
        if api.poll() is not None or any(
            process.poll() is not None for _, _, process in workers
        ):
            break
        if all(process.poll() is None for _, _, process in workers):
            time.sleep(0.5)
            if all(process.poll() is None for _, _, process in workers):
                print(f"财务 Skill 平台已启动：http://127.0.0.1:{port}")
                if host in {"0.0.0.0", "::"}:
                    print("服务已监听局域网地址，其他设备请使用本机 WLAN IPv4 地址访问。")
                print(f"API PID={api.pid}，Worker 数量={len(workers)}")
                for pool, worker_id, process in workers:
                    print(f"  {worker_id}: PID={process.pid}，池={pool}")
                if open_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}")
                return 0

    for process in (api, *(item[2] for item in workers)):
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
    for process_id, hints in runtime_processes(runtime):
        if process_matches(process_id, *hints):
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
        elif process_exists(process_id):
            print(f"跳过过期 PID {process_id}：当前进程不属于财务 Skill 平台。")
    RUNTIME_FILE.unlink(missing_ok=True)
    print("财务 Skill 平台已停止。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="财务 Skill 平台本地进程管理")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--port", type=int, default=8000)
    start_parser.add_argument(
        "--host",
        default=os.getenv("FINANCIAL_HOST", "0.0.0.0"),
        help="API 监听地址；0.0.0.0 允许局域网访问。",
    )
    start_parser.add_argument("--no-browser", action="store_true")
    commands.add_parser("stop")
    args = parser.parse_args()
    if args.command == "start":
        return start(args.port, args.host, not args.no_browser)
    return stop()


if __name__ == "__main__":
    raise SystemExit(main())
