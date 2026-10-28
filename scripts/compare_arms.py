#!/usr/bin/env python3
"""Print one comparison table across several controller arms.

Reads the archived run records of each arm and puts them side by side, so the
difference between controllers is visible per goal instead of across three separate
tables. Uses the same classification rules as scripts/summarize_results.py: a run
counts only if the action itself returned, and action_status 6 is a real navigation
failure rather than a missing result.

Usage:
    /usr/bin/python3 scripts/compare_arms.py \
        mppi=results/archive/ctl_mppi/runs \
        rpp=results/archive/ctl_rpp/runs \
        graceful=results/archive/ctl_graceful/runs
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from summarize_results import ROOT, load_goals  # noqa: E402

import run_record  # noqa: E402

import json  # noqa: E402


def load_arm(path):
    """Return {goal_id: record} for the records that hold a navigation result."""
    out = {}
    for f in sorted(Path(path).glob("*/run.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        verdict, _ = run_record.verdict(rec)
        if verdict not in run_record.SAFE_VERDICTS:
            continue
        out[rec.get("goal_id")] = (verdict, rec)
    return out


def cell(entry):
    if entry is None:
        return "-"
    verdict, rec = entry
    if verdict != "succeeded":
        return "**失败**"
    t = rec.get("nav_time_sim_s")
    r = rec.get("recoveries")
    t = "%.1f s" % t if isinstance(t, (int, float)) else "?"
    r = "%s" % r if isinstance(r, (int, float)) else "?"
    return "%s / %s 次" % (t, r)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    arms = []
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print("参数格式应为 name=path，收到：%s" % arg)
            return 2
        name, path = arg.split("=", 1)
        arms.append((name, load_arm(path), path))

    order, planned, cats = load_goals(ROOT / "config" / "navigation_goals.yaml")

    header = "| 目标 | 类别 | 规划路径 | " + " | ".join(n for n, _, _ in arms) + " |"
    print(header)
    print("| --- | --- | --- | " + " | ".join("---" for _ in arms) + " |")

    for gid in order:
        row = [gid, cats[gid], "%.2f m" % planned[gid]]
        row += [cell(a[1].get(gid)) for a in arms]
        print("| " + " | ".join(row) + " |")

    print()
    for name, data, path in arms:
        ok = sum(1 for v, _ in data.values() if v == "succeeded")
        print("%-9s 记录 %d 条，成功 %d 条  (%s)" % (name, len(data), ok, path))

    # Averages are only comparable across the goals every arm completed. Averaging an
    # arm over a goal set the others failed is how a comparison quietly turns into a
    # ranking of which arm got lucky.
    common = [gid for gid in order
              if all(a[1].get(gid) and a[1][gid][0] == "succeeded" for a in arms)]
    print()
    print("全部臂都成功的目标：%d 个（%s）" % (len(common), " ".join(common) if common else "无"))
    if common:
        print()
        print("| 臂 | 成功数 | 共同目标上的平均耗时 | 平均恢复次数 |")
        print("| --- | --- | --- | --- |")
        for name, data, _ in arms:
            times = [data[g][1].get("nav_time_sim_s") for g in common]
            recs = [data[g][1].get("recoveries") for g in common]
            times = [t for t in times if isinstance(t, (int, float))]
            recs = [r for r in recs if isinstance(r, (int, float))]
            ok = sum(1 for v, _ in data.values() if v == "succeeded")
            print("| %s | %d / %d | %.1f s | %.2f |"
                  % (name, ok, len(data),
                     sum(times) / len(times) if times else 0,
                     sum(recs) / len(recs) if recs else 0))

    print()
    print("单元格格式：导航耗时（仿真时间）/ 恢复次数。「失败」表示动作返回了但没有成功，")
    print("是真实导航失败；「-」表示该臂没有这条记录（例如启动失败后未补跑）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
