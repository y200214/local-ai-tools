"""停止したローカルサービスを再起動する。稼働中のプロセスは終了しない。

無指定は確認のみ。--fix は停止中・有効なタスクだけを開始する。
管理者がサービスのタスクを無効にした場合は保守停止として尊重する。
記録は日時・タスク状態・終了コード・ポート状態のみ。本文や秘密は記録しない。
"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
TASK = "minutes-pipeline-local-services"
PORTS = (8010, 8008)
LOG = ROOT / "logs" / "local_services_watchdog.jsonl"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=20, creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("task_command_failed")
    return result.stdout.strip()


def task_state() -> dict:
    return json.loads(powershell(
        "$ErrorActionPreference='Stop';"
        "$t=Get-ScheduledTask -TaskName '" + TASK + "';"
        "$i=Get-ScheduledTaskInfo -TaskName '" + TASK + "';"
        "@{state=[string]$t.State;enabled=[bool]$t.Settings.Enabled;"
        "last_result=[long]$i.LastTaskResult;"
        "last_run=$i.LastRunTime.ToString('s')}|ConvertTo-Json -Compress"
    ))


def reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def start_task() -> None:
    powershell("$ErrorActionPreference='Stop';Start-ScheduledTask -TaskName '" + TASK + "'")


def decide(state: dict, ports: list[bool]) -> str:
    if not state.get("enabled") or state.get("state") == "Disabled":
        return "maintenance"
    if all(ports):
        return "healthy"
    if state.get("state") in ("Running", "Queued"):
        return "running_unavailable"
    if any(ports):
        return "partial_listener"
    if state.get("state") != "Ready":
        return "unknown_state"
    return "stopped"


def record(event: str, state: dict, ports: list[bool]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    logger = logging.getLogger("local_services_watchdog")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info(json.dumps({
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event,
            "state": state.get("state"), "last_result": state.get("last_result"),
            "last_run": state.get("last_run"), "ports": dict(zip(PORTS, ports)),
        }))
    finally:
        logger.removeHandler(handler)
        handler.close()


def check(fix: bool = False) -> str:
    state = task_state()
    ports = [reachable(port) for port in PORTS]
    decision = decide(state, ports)
    record(decision, state, ports)
    if decision == "stopped" and fix:
        # 開始要求の直前にも確認し、他の起動操作と競合しない。
        latest = task_state()
        if decide(latest, [reachable(port) for port in PORTS]) != "stopped":
            return "state_changed"
        record("start_requested", state, ports)
        start_task()
        for _ in range(10):
            time.sleep(1)
            after = [reachable(port) for port in PORTS]
            if all(after):
                record("recovered", task_state(), after)
                return "recovered"
        record("start_unconfirmed", task_state(), after)
        return "start_unconfirmed"
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    try:
        result = check(args.fix)
    except Exception as error:
        record("monitor_error:" + type(error).__name__, {}, [])
        return 1
    return 0 if result in ("healthy", "maintenance", "recovered", "state_changed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
