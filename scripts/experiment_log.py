#!/usr/bin/env python3
"""Local experiment-run ledger for turtlebot4-navlab (no ROS dependencies).

Commands:
  python3 scripts/experiment_log.py start --goal-id exploratory --trial 1
  python3 scripts/experiment_log.py finish --run-id <ID> --outcome succeeded --nav-time-sim 19 --recoveries 1 --remaining-distance 0.03
  python3 scripts/experiment_log.py list

Only explicitly confirmed outcome/metrics are entered into the summary CSV.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
from contextlib import contextmanager
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
RUNS = RESULTS / "runs"
SUMMARY = RESULTS / "summary.csv"
FIELDS = [
    "run_id", "goal_id", "trial", "outcome", "started_utc", "finished_utc",
    "duration_wall_s", "nav_time_sim_s", "remaining_distance_m", "recoveries",
    "collisions", "path_length_m", "gazebo_rtf", "git_commit", "launch_log", "notes",
]


def now_utc():
    return datetime.now(timezone.utc)


def timestamp(t):
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def git_head():
    try:
        return subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def safe_name(s):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", s):
        raise ValueError("goal-id must be 1-64 chars: letters, digits, _ . -")
    return s


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".experiment-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_dir_for(run_id):
    if run_id in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise ValueError("Invalid run id")
    return RUNS / run_id


def start(args):
    goal = safe_name(args.goal_id)
    if args.trial < 1:
        raise ValueError("trial must be >=1")
    t = now_utc()
    run_id = f"{t.strftime('%Y%m%dT%H%M%SZ')}_{goal}_t{args.trial:02d}_{uuid.uuid4().hex[:6]}"
    directory = run_dir_for(run_id)
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "run_id": run_id, "goal_id": goal, "trial": args.trial,
        "state": "running", "started_utc": timestamp(t),
        "git_commit": git_head(), "launch_log": args.launch_log or "",
        "notes_start": args.notes or "",
    }
    write_json_atomic(directory / "run.json", record)
    print(f"RUN_ID={run_id}")
    print(f"记录目录: {directory}")
    print("自动执行将记录结果。" if getattr(args, "command", None) == "navigate" else "本次导航结束后运行 finish；不要把还没测到的数值填为 0。")
    return record


@contextmanager
def ledger_lock():
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with (SUMMARY.parent / ".experiment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def checkpoint(run_id, extra):
    with ledger_lock():
        path = run_dir_for(run_id) / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] == "finished":
            raise ValueError("Run already finished")
        record.update(extra)
        write_json_atomic(path, record)


def sync_summary(record):
    # Called under ledger_lock. Rewrite atomically so a crash cannot leave half a row.
    rows = []
    if SUMMARY.exists():
        with SUMMARY.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames and reader.fieldnames != FIELDS:
                raise ValueError("summary.csv header differs from expected schema")
    if any(r["run_id"] == record["run_id"] for r in rows):
        return
    row = {k: record.get(k) for k in FIELDS}
    row["notes"] = "; ".join(filter(None, [record.get("notes_start"), record.get("notes_finish")]))
    rows.append({k: "" if v is None else v for k, v in row.items()})
    fd, tmp = tempfile.mkstemp(prefix=".summary-", dir=SUMMARY.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SUMMARY)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def finalize(run_id, outcome, extra=None):
    if outcome not in ("succeeded", "failed", "canceled"):
        raise ValueError("Invalid outcome")
    with ledger_lock():
        path = run_dir_for(run_id) / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["state"] != "finished":
            record.update(extra or {})
            t = now_utc()
            started = datetime.fromisoformat(record["started_utc"].replace("Z", "+00:00"))
            record.update(state="finished", outcome=outcome, finished_utc=timestamp(t))
            record.setdefault("duration_wall_s", round((t - started).total_seconds(), 3))
            for k in ("nav_time_sim_s", "remaining_distance_m", "recoveries", "collisions", "path_length_m", "gazebo_rtf"):
                record.setdefault(k, None)
            write_json_atomic(path, record)
        # JSON is authoritative. Retry repairs a crash between JSON and CSV writes.
        sync_summary(record)
    print(f"结果已记录：{path}")
    return record


def finish(args):
    import math
    metrics = {}
    for arg, field in (("nav_time_sim", "nav_time_sim_s"), ("remaining_distance", "remaining_distance_m"),
                       ("path_length", "path_length_m"), ("gazebo_rtf", "gazebo_rtf"),
                       ("recoveries", "recoveries"), ("collisions", "collisions")):
        value = getattr(args, arg)
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{arg} must be finite and >=0")
        if value is not None:
            metrics[field] = value
    metrics["notes_finish"] = args.notes or ""
    finalize(args.run_id, args.outcome, metrics)


def recover(args):
    path = run_dir_for(args.run_id) / "run.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("state") != "finished":
        raise ValueError("Running records require explicit finish; never infer a terminal Action status")
    finalize(args.run_id, record["outcome"])


def list_runs(_args):
    if not RUNS.exists():
        print("暂无实验记录")
        return
    found = False
    for run in sorted(RUNS.glob("*/run.json")):
        x = json.loads(run.read_text(encoding="utf-8"))
        print(x["run_id"], x["state"], x.get("outcome", ""))
        found = True
    if not found:
        print("暂无实验记录")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start", help="创建一次实验记录")
    p.add_argument("--goal-id", default="exploratory", help="目标 ID，尚未固定目标时可用 exploratory")
    p.add_argument("--trial", type=int, default=1)
    p.add_argument("--launch-log", default="", help="已有一键启动脚本的日志绝对路径，可留空")
    p.add_argument("--notes", default="")
    p.set_defaults(func=start)
    p = sub.add_parser("finish", help="登记人工确认的结果")
    p.add_argument("--run-id", required=True)
    p.add_argument("--outcome", required=True, choices=["succeeded", "failed", "canceled"])
    p.add_argument("--nav-time-sim", type=float, default=None, help="RViz 显示的导航耗时，单位秒")
    p.add_argument("--remaining-distance", type=float, default=None, help="终态剩余距离，m")
    p.add_argument("--recoveries", type=int, default=None)
    p.add_argument("--collisions", type=int, default=None, help="只有实际计数已知时填写")
    p.add_argument("--path-length", type=float, default=None)
    p.add_argument("--gazebo-rtf", type=float, default=None, help="RTF，如 0.4，不是 40")
    p.add_argument("--notes", default="")
    p.set_defaults(func=finish)
    p = sub.add_parser("list", help="列出实验记录")
    p.set_defaults(func=list_runs)
    p = sub.add_parser("navigate", help="执行一个真实 NavigateToPose 任务并自动记录")
    from navigation_run import add_arguments, execute
    add_arguments(p)
    p.set_defaults(func=lambda args: execute(args, sys.modules[__name__]))
    p = sub.add_parser("recover", help="从已结束 JSON 恢复缺失的汇总行")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=recover)
    args = parser.parse_args()
    try:
        result = args.func(args)
        if isinstance(result, int):
            sys.exit(result)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
