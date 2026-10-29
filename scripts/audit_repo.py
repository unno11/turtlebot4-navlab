#!/usr/bin/env python3
"""Static self-check for this repository.

Everything here runs without a simulator: it compares the repository against
itself - tracked files, docs, links, configuration, and the numbers the docs
quote. Anything that needs Gazebo (goal-set drift, run results) is out of scope.

Exit code is 1 when a problem is found, so CI can gate on it.
"""

import argparse
import ast
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_FILES = ["README.md"] + sorted(glob.glob("docs/*.md")) + sorted(glob.glob("results/*.md"))


class Report:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.problems = []
        self.warnings = []

    def say(self, msg):
        if self.verbose:
            print("   " + msg)

    def head(self, msg):
        if self.verbose:
            print(f"\n{msg}")

    def problem(self, area, msg):
        self.problems.append(f"[{area}] {msg}")

    def warn(self, area, msg):
        self.warnings.append(f"[{area}] {msg}")


def rel(path):
    return os.path.relpath(path, ROOT)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


# ------------------------------------------------------------------ 1. files
def check_inventory(rep):
    rep.head("1. 跟踪文件")
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        rep.say("不是 git 工作区，跳过")
        return
    r = git("ls-files")
    if r.returncode:
        rep.problem("inventory", f"git ls-files 失败: {r.stderr.strip()[:80]}")
        return
    files = r.stdout.split()
    rep.say(f"跟踪文件 {len(files)} 个")
    for f in files:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            rep.problem("inventory", f"跟踪但不存在: {f}")
        elif os.path.getsize(p) > 1_500_000:
            rep.warn("inventory", f"大文件 {os.path.getsize(p) / 1048576:.2f} MB: {f}")
    for f in files:
        if re.search(r"(\.log$|\.mp4$|\.pyc$|__pycache__|\.bag$|^results/summary\.csv$)", f):
            rep.problem("inventory", f"不应入库: {f}")
    untracked = [l for l in git("status", "--porcelain").stdout.splitlines() if l.startswith("??")]
    for line in untracked:
        rep.say(f"未跟踪: {line[3:]}")


# --------------------------------------------------------------- 2. ignore
def check_gitignore(rep):
    rep.head("2. .gitignore")
    p = os.path.join(ROOT, ".gitignore")
    if not os.path.exists(p):
        rep.problem("gitignore", "缺少 .gitignore")
        return
    text = read(p)
    for need in ("results/runs", "results/archive", "__pycache__"):
        if need not in text:
            rep.problem("gitignore", f"缺少规则 {need}")


# ----------------------------------------------------------------- 3. voice
VOICE = re.compile(r"(我们|本人|复盘|笔记|TODO|FIXME|我觉得|大概)")
STALE = [
    (r"只有\s*MPPI", "「只有 MPPI」类结论已在复跑中推翻"),
    (r"说明不了任何事", "基线成功仍有意义，措辞过强"),
    (r"不反映控制律", "因果表述强于证据"),
    (r"不受 RTF 直接影响", "仿真时间仍受丢指令影响"),
]


def check_text(rep):
    rep.head("3. 文档口吻与过时表述")
    for f in MD_FILES:
        for i, line in enumerate(read(os.path.join(ROOT, f)).splitlines(), 1):
            m = VOICE.search(line)
            if m:
                rep.problem("voice", f"{f}:{i} 内部用语「{m.group(0)}」")
            if re.search(r"(?<![自文])我(?!方)", line):
                rep.problem("voice", f"{f}:{i} 第一人称")
            for pat, why in STALE:
                if re.search(pat, line):
                    rep.warn("stale", f"{f}:{i} {why}")
    rep.say(f"扫描 {len(MD_FILES)} 个 md")


# ----------------------------------------------------------------- 4. links
def slug(heading):
    s = heading.strip().lower()
    s = re.sub(r"[`*_~]", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff \-]", "", s)
    return s.replace(" ", "-")


def check_links(rep):
    rep.head("4. 链接与锚点")
    dead = anchors = 0
    for f in MD_FILES:
        base = os.path.dirname(os.path.join(ROOT, f))
        for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)\)", read(os.path.join(ROOT, f))):
            target = m.group(1)
            if target.startswith(("http", "mailto")):
                continue
            path, _, anchor = target.partition("#")
            dest = os.path.join(base, path) if path else os.path.join(ROOT, f)
            if not os.path.exists(dest):
                rep.problem("links", f"{f}: 死链 {target}")
                dead += 1
                continue
            if anchor and dest.endswith(".md"):
                heads = re.findall(r"^#+\s+(.*)$", read(dest), re.M)
                anchors += 1
                if anchor not in {slug(h) for h in heads}:
                    rep.problem("links", f"{f}: 锚点不存在 {target}")
    rep.say(f"死链 {dead} 处，锚点 {anchors} 个")


# ------------------------------------------------------------------ 5. code
def check_code(rep):
    rep.head("5. 脚本语法与权限")
    shells = sorted(glob.glob(os.path.join(ROOT, "scripts/*.sh")))
    for path in shells:
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        if r.returncode:
            rep.problem("code", f"bash -n 失败 {rel(path)}: {r.stderr.strip()[:100]}")
        if os.name != "nt":
            mode = oct(os.stat(path).st_mode)[-3:]
            if mode != "755":
                rep.problem("code", f"{rel(path)} 权限 {mode}，应为 755")
    pys = sorted(glob.glob(os.path.join(ROOT, "scripts/*.py")))
    for path in pys:
        try:
            ast.parse(read(path), filename=path)
        except SyntaxError as exc:
            rep.problem("code", f"语法错误 {rel(path)}:{exc.lineno}: {exc.msg}")
    rep.say(f"{len(shells)} 个 .sh，{len(pys)} 个 .py")


# ---------------------------------------------------------------- 6. config
def check_config(rep):
    rep.head("6. 配置")
    try:
        import yaml
    except ImportError:
        rep.warn("config", "未安装 PyYAML，跳过配置检查")
        return
    goals_path = os.path.join(ROOT, "config/navigation_goals.yaml")
    goals = yaml.safe_load(read(goals_path))
    raw = goals.get("goals", {})
    if isinstance(raw, dict):
        ids = list(raw.keys())
    else:
        ids = [g.get("id") for g in raw if isinstance(g, dict)]
    if len(ids) != 8:
        rep.problem("config", f"navigation_goals.yaml 目标数 {len(ids)}，应为 8")
    start = goals.get("start", {})
    if (start.get("x"), start.get("y"), start.get("yaw")) != (0.0, 0.0, 0.0):
        rep.problem("config", f"start 不是 S0=(0,0,0): {start}")
    loc = read(os.path.join(ROOT, "config/localization.yaml"))
    if "set_initial_pose: true" not in loc:
        rep.problem("config", "localization.yaml 未开启 set_initial_pose")
    rep.say(f"目标 {len(ids)} 个，start=S0")

    arms = {}
    for arm in ("mppi", "rpp", "graceful"):
        path = os.path.join(ROOT, f"config/nav2_{arm}.yaml")
        if not os.path.exists(path):
            rep.problem("config", f"缺少 config/nav2_{arm}.yaml")
            continue
        params = yaml.safe_load(read(path))["controller_server"]["ros__parameters"]
        arms[arm] = params
        rep.say(f"{arm}: {params['FollowPath']['plugin']}")
    if len(arms) == 3:
        if len({p["FollowPath"]["plugin"] for p in arms.values()}) != 3:
            rep.problem("config", "三个臂的 FollowPath 插件不是三个不同实现")
        base_name, base = next(iter(arms.items()))
        base_rest = {k: v for k, v in base.items() if k != "FollowPath"}
        for name, params in arms.items():
            rest = {k: v for k, v in params.items() if k != "FollowPath"}
            if rest != base_rest:
                diff = {k for k in set(rest) | set(base_rest) if rest.get(k) != base_rest.get(k)}
                rep.problem("config", f"nav2_{name}.yaml 与 nav2_{base_name}.yaml 除 FollowPath 外仍有差异: {sorted(diff)}")


# ------------------------------------------------------------- 7. doc refs
def check_refs(rep):
    rep.head("7. 文档引用")
    refs = set()
    codes = {}
    for f in MD_FILES:
        text = read(os.path.join(ROOT, f))
        refs |= set(re.findall(r"scripts/[\w./-]+\.(?:sh|py)", text))
        codes[f] = "\n".join(re.findall(r"```[a-z]*\n(.*?)```", text, re.S))
    missing = sorted(r for r in refs if not os.path.exists(os.path.join(ROOT, r)))
    for m in missing:
        rep.problem("refs", f"文档引用但不存在: {m}")
    rep.say(f"引用 {len(refs)} 个脚本，缺失 {len(missing)} 个")

    shells = "\n".join(read(p) for p in glob.glob(os.path.join(ROOT, "scripts/*.sh")))
    env_vars = set()
    for code in codes.values():
        for line in code.splitlines():
            if "scripts/" not in line:
                continue
            # assignments that prefix the command, not variables printed as output
            for var in re.findall(r"\b([A-Z][A-Z0-9_]{2,})=", line.split("scripts/")[0]):
                env_vars.add(var)
    for var in sorted(env_vars):
        if var not in shells:
            rep.problem("refs", f"文档里用到 {var}=…，但没有任何脚本读取它")
    rep.say(f"文档中的环境开关 {len(env_vars)} 个: {', '.join(sorted(env_vars))}")

    goal_doc = os.path.join(ROOT, "docs/goal_set.md")
    if os.path.exists(goal_doc):
        doc_ids = set(re.findall(r"\bG0\d\b", read(goal_doc)))
        cfg_text = read(os.path.join(ROOT, "config/navigation_goals.yaml"))
        cfg_ids = set(re.findall(r"^  (G0\d):", cfg_text, re.M))
        if doc_ids != cfg_ids:
            rep.problem("refs", f"docs/goal_set.md 目标集 {sorted(doc_ids)} 与配置 {sorted(cfg_ids)} 不一致")


# ------------------------------------------------------------------ 8. data
def check_data(rep):
    rep.head("8. 数字一致性")
    runs = os.path.join(ROOT, "results/archive/baseline_v1/runs")
    if not os.path.isdir(runs):
        rep.say("本地无基线归档，跳过（CI 中属正常）")
        return
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/summarize_results.py"),
                        "--runs", runs], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        rep.problem("data", f"summarize_results.py 失败: {r.stderr.strip()[:100]}")
        return
    total = sum(int(n) for n in re.findall(r"\|\s*G0\d\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|", r.stdout))
    rep.say(f"基线试验合计 {total}")
    if total and total != 24:
        rep.problem("data", f"基线试验合计 {total}，README 写 24 次")


def main():
    ap = argparse.ArgumentParser(description="仓库静态自检（不需要仿真）")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每一项的细节")
    args = ap.parse_args()
    rep = Report(verbose=args.verbose)
    os.chdir(ROOT)
    checks = [check_inventory, check_gitignore, check_text, check_links, check_code,
              check_config, check_refs, check_data]
    for check in checks:
        try:
            check(rep)
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide the others
            rep.problem("audit", f"{check.__name__} 异常: {exc}")

    print()
    if rep.warnings:
        print(f"{len(rep.warnings)} 条提示:")
        for w in rep.warnings:
            print("  - " + w)
    if rep.problems:
        print(f"\n{len(rep.problems)} 个问题:")
        for p in rep.problems:
            print("  - " + p)
        return 1
    print("检查通过，未发现问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
