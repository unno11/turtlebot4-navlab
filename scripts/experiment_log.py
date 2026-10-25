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
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
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
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_dir_for(run_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
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
    print("本次导航结束后运行 finish；不要把还没测到的数值填为 0。")


def finish(args):
    directory = run_dir_for(args.run_id)
    path = directory / "run.json"
    if not path.is_file():
        raise ValueError(f"Run not found: {args.run_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("state") == "finished":
        raise ValueError("Run already finished; not adding a duplicate summary row")
    for key in ("nav_time_sim", "remaining_distance", "path_length", "gazebo_rtf"):
        value = getattr(args, key)
        if value is not None and value < 0:
            raise ValueError(f"{key} must be >=0")
    for key in ("recoveries", "collisions"):
        value = getattr(args, key)
        if value is not None and value < 0:
            raise ValueError(f"{key} must be >=0")
    t = now_utc()
    start_time = datetime.fromisoformat(record["started_utc"].replace("Z", "+00:00"))
    record.update({
        "state": "finished", "outcome": args.outcome,
        "finished_utc": timestamp(t),
        "duration_wall_s": round((t - start_time).total_seconds(), 3),
        "nav_time_sim_s": args.nav_time_sim,
        "remaining_distance_m": args.remaining_distance,
        "recoveries": args.recoveries,
        "collisions": args.collisions,
        "path_length_m": args.path_length,
        "gazebo_rtf": args.gazebo_rtf,
        "notes_finish": args.notes or "",
    })
    row = {
        "run_id": record["run_id"], "goal_id": record["goal_id"],
        "trial": record["trial"], "outcome": record["outcome"],
        "started_utc": record["started_utc"], "finished_utc": record["finished_utc"],
        "duration_wall_s": record["duration_wall_s"],
        "nav_time_sim_s": record["nav_time_sim_s"],
        "remaining_distance_m": record["remaining_distance_m"],
        "recoveries": record["recoveries"], "collisions": record["collisions"],
        "path_length_m": record["path_length_m"], "gazebo_rtf": record["gazebo_rtf"],
        "git_commit": record["git_commit"], "launch_log": record["launch_log"],
        "notes": "; ".join(filter(None, [record.get("notes_start"), record.get("notes_finish")]))
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("a+", encoding="utf-8", newline="") as f:
        f.seek(0)
        reader = csv.DictReader(f)
        if f.readable():
            existing_rows = list(reader)
            if reader.fieldnames and reader.fieldnames != FIELDS:
                raise ValueError("summary.csv header differs from expected schema")
            if any(x["run_id"] == record["run_id"] for x in existing_rows):
                write_json_atomic(path, record)
                print("结果已在 summary.csv 中；不会重复追加")
                return
        f.seek(0, 2)
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    write_json_atomic(path, record)
    print(f"结果已记录：{path}")
    print(f"汇总已追加：{SUMMARY}")


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
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
