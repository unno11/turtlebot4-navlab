#!/usr/bin/env python3
"""Summarise the local experiment records into the baseline table.

Reads the per-run records in results/runs/*/run.json (local only, excluded from
Git) together with the goal set in config/navigation_goals.yaml, and prints a
markdown table plus a totals row. Nothing is hard-coded, so the numbers can
always be re-derived from the raw records.

Classification follows docs/experiment_logging.md and uses the JSON, which is
authoritative:

  * a run counts only if the Action itself returned
    (termination_reason == "action_result")
  * action_status 4 -> succeeded, 6 -> failed
  * anything else (wall_timeout, stream stall, recorder never connected) is a
    record without a navigation result and is listed separately

The CSV `outcome` column alone cannot make this distinction: a run aborted by the
wall-clock budget is stored as "failed" there, which would silently pollute the
success rate.

Usage:
    /usr/bin/python3 scripts/summarize_results.py
    /usr/bin/python3 scripts/summarize_results.py --runs /path/to/runs
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS_WORD = {4: "succeeded", 6: "failed"}


def load_goals(path):
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    order = list(cfg["goals"].keys())
    planned = {gid: g["measures"]["path_len_m"] for gid, g in cfg["goals"].items()}
    cats = {gid: g["category"] for gid, g in cfg["goals"].items()}
    return order, planned, cats


def classify(rec):
    """Return (verdict, reason). verdict in {succeeded, failed, excluded}."""
    if rec.get("state") != "finished":
        return "excluded", "state=%s" % rec.get("state")
    if rec.get("termination_reason") != "action_result":
        return "excluded", str(rec.get("termination_reason") or "no_action_result")
    status = rec.get("action_status")
    word = STATUS_WORD.get(status)
    if word is None:
        return "excluded", "action_status=%s" % status
    return word, ""


def span(values, fmt="%.1f"):
    if not values:
        return "-"
    if len(values) == 1:
        return fmt % values[0]
    return ("%s (" + fmt + "–" + fmt + ")") % (
        fmt % statistics.mean(values), min(values), max(values))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(ROOT / "results" / "runs"))
    args = ap.parse_args()

    order, planned, cats = load_goals(ROOT / "config" / "navigation_goals.yaml")

    per_goal = {gid: [] for gid in order}
    excluded = []
    for path in sorted(Path(args.runs).glob("*/run.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        gid = rec.get("goal_id")
        if gid not in per_goal:
            continue
        verdict, reason = classify(rec)
        if verdict == "excluded":
            excluded.append("%s t%s (%s)" % (gid, rec.get("trial"), reason))
            continue
        per_goal[gid].append((verdict, rec))

    print("| 目标 | 类别 | 规划路径 | 试验 | 成功 | 成功率 | 导航耗时 s | 恢复次数 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")

    total_trials = total_ok = 0
    all_time, all_rec = [], []
    for gid in order:
        rs = per_goal[gid]
        if not rs:
            print("| %s | %s | %.2f m | 0 | 0 | - | - | - |"
                  % (gid, cats[gid], planned[gid]))
            continue
        ok = [rec for verdict, rec in rs if verdict == "succeeded"]
        times = [rec["nav_time_sim_s"] for rec in ok
                 if isinstance(rec.get("nav_time_sim_s"), (int, float))]
        recs = [rec["recoveries"] for rec in ok
                if isinstance(rec.get("recoveries"), (int, float))]
        total_trials += len(rs)
        total_ok += len(ok)
        all_time += times
        all_rec += recs
        print("| %s | %s | %.2f m | %d | %d | %.0f%% | %s | %s |"
              % (gid, cats[gid], planned[gid], len(rs), len(ok),
                 100.0 * len(ok) / len(rs), span(times), span(recs, "%.0f")))

    if total_trials:
        print("| **合计** | | **%.1f m** | **%d** | **%d** | **%.0f%%** | %s | %s |"
              % (sum(planned.values()), total_trials, total_ok,
                 100.0 * total_ok / total_trials, span(all_time),
                 span(all_rec, "%.0f")))

    print()
    print("碰撞次数不在本表中：自动记录没有可靠的碰撞来源，CSV 中保持为空，"
          "空值表示未知，不等于零。")
    if excluded:
        print()
        print("未计入的本地记录（没有形成导航结果）：" + "、".join(excluded))
    return 0 if total_trials else 1


if __name__ == "__main__":
    sys.exit(main())
