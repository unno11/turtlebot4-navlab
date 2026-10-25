# 建立实验日志和结果目录

此步骤只建立**记录设施**，尚未冻结 5–10 个目标点、重复次数或统计协议。保留已有的 `scripts/start_navigation.sh`、`scripts/manage_ogre2.py`、`patches/`，不要覆盖它们。

## 目录

```text
results/
  README.md                  # 字段定义与边界
  summary.csv                # 小型汇总表（可以提交 Git）
  runs/                      # 每次运行的独立记录（由 Git 忽略）
    <run_id>/run.json
scripts/experiment_log.py    # 创建、结束、列出实验记录
```

当前一键启动脚本的日志位置仍是 `~/turtlebot4_ws/log/navlab/`，不是这个仓库。不要让一键启动命令与本实验记录工具互相接管进程。

## 使用方法

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
# 按当前一键启动脚本照常运行 Gazebo/AMCL/Nav2/RViz
./scripts/start_navigation.sh
```

另开终端，在**发送 Nav2 Goal 之前**执行：

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
python3 scripts/experiment_log.py start --goal-id exploratory --trial 1
```

它输出 `RUN_ID=...`。复制该 ID。若需要关联已有原始启动日志，可追加 `--launch-log /home/tsy/turtlebot4_ws/log/navlab/navigation_....log`。之后在 RViz 里发 Goal，记录实际状态，导航完成或取消后登记（示例数值仅为演示，不能照抄为真实实验）：

```bash
python3 scripts/experiment_log.py finish \
  --run-id "你刚才得到的RUN_ID" \
  --outcome succeeded \
  --nav-time-sim 19 \
  --remaining-distance 0.03 \
  --recoveries 1 \
  --notes "人工确认Reached；示例，请替换"
```

未测得的碰撞次数、路径长度和 RTF 不传入；默认记录为空值。对于失败和取消用 `--outcome failed` 或 `--outcome canceled`，不要把失败自动归为碰撞。

查看记录：

```bash
python3 scripts/experiment_log.py list
column -s, -t < results/summary.csv | head -15
```

## 与 Git 的关系

向原有 `.gitignore` 追加（只追加一次）这一行，避免把每轮原始记录全部推送：

```gitignore
/results/runs/
```

`results/summary.csv` 和 `results/README.md` 应当保留在 Git 仓库，可作为阶段性小型结果汇总。`runs/` 可在本地或私人存储保留原始文件；重要实验建议将原始记录另外备份，不要仅依赖 WSL 硬盘。

## 验收

1. `python3 scripts/experiment_log.py --help` 正常。
2. `results/summary.csv` 只有表头，不含虚构的数据。
3. 试运行 `start` 后出现唯一 `run_id` 和 JSON 文件。
4. 在真实导航后执行 `finish`，汇总表只增加 1 行；再次执行不会重复写入。
5. `git status` 不出现 `results/runs/` 下的原始文件，Git 仅识别脚本、文档及小型汇总表。
