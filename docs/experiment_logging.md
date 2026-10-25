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

## 自动执行单个 NavigateToPose 任务

保留 `start`、`finish`、`list`。自动入口使用同一个 ledger、run.json 和 summary.csv，不需要先运行 `start`，也不要在 RViz 同时发送另一个目标。先按 reproduction.md 启动并完成人工 AMCL 初始化，再在新终端执行：

```bash
source /opt/ros/jazzy/setup.bash
source ~/turtlebot4_ws/install/setup.bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
# 输入自行确认的安全目标 x y yaw（米、米、弧度），本次不冻结目标集
read -r GOAL_X GOAL_Y GOAL_YAW
/usr/bin/python3 scripts/experiment_log.py navigate \
  --goal-id exploratory --trial 1 \
  --x "$GOAL_X" --y "$GOAL_Y" --yaw "$GOAL_YAW" \
  --timeout 300 --stale-timeout 30
```

可用 `--launch-log /绝对路径/navigation_....log` 关联已有日志。默认使用 `/navigate_to_pose`、`/odom`、`/clock` 和 map frame；命名空间可通过 `--action`、`--odom`、`--frame` 调整。仿真时钟 topic 当前固定为 `/clock`。退出码成功为 0，其余为 1。所有超时均用 monotonic 现实时间，仿真暂停也会触发超时。

| 字段 | 自动来源及边界 |
| --- | --- |
| outcome | Action 状态 4→succeeded，5→canceled，其他→failed；超时/数据中断即使取消成功仍是 failed |
| action_status | run.json 内保存原始 Action 状态；没有收到终态为 null，绝不臆造 aborted/canceled |
| nav_time_sim_s | 最后收到的 NavigateToPose feedback.navigation_time，使用仿真时钟；不是墙钟，也不保证等于精确终态耗时 |
| remaining_distance_m / recoveries | 最后反馈的 distance_remaining / number_of_recoveries，非自行估算；无反馈为 null |
| duration_wall_s | 自动记录创建后到结束（包括等待服务器和取消宽限）的 monotonic 墙钟秒；手工 finish 仍采用 UTC 起止差 |
| path_length_m | Goal 被接受后 `/odom` 相邻位置的平面距离累加；至少两个样本，否则 null；仅为里程计估计，不是 Gazebo Ground Truth |
| collisions / gazebo_rtf | 无可靠数据源，JSON null，CSV 空单元格；Collision Monitor 介入次数不等于碰撞数 |
| Git / Goal / Trial / 时间 | 完整运行时 Git HEAD、人工 goal_id、Action UUID、目标位姿、trial、UTC 起止；目标接受时间另存 |

run.json 还保存来源、反馈接收时间、里程计样本数、终止原因、Nav2 error_code/error_msg（可用时）、取消结果和最后 heartbeat。CSV 列及原字段含义保持不变，异常原因写入 notes；额外详情在 JSON。CSV 空值表示未知，不是零。

SIGINT/SIGTERM 会请求取消并在 `--cancel-grace`（默认 5 墙钟秒）内等待终态。只有收到状态 5 才确认取消。节点退出、服务器失联、仿真时钟不前进或 odom 中断记录为 failed，并保留已采集指标；不能仅凭数据流中断认定 Gazebo 已崩溃。ROS 上下文退出后不能发送取消；未收到接受应答或取消终态时，目标可能仍执行，需人工检查机器人和服务器。

路径是采样近似：丢包会低估曲线路径，漂移或定位跳变会污染估计。odom frame 变化、时间倒退或非有限坐标会使路径值无效并写 null。工具不会修改 Collision Monitor、控制器或导航算法。

### 持久化与中断恢复

结束时先原子保存 JSON，再在文件锁内原子重写 CSV；相同 run_id 幂等，CSV 不重复追加，历史行保留。若 JSON 已结束而写 CSV 时断电，下次执行：

```bash
python3 scripts/experiment_log.py recover --run-id "$RUN_ID"
```

`recover` 仅修复已结束记录的汇总；不推断 running 记录是否已成功。SIGKILL、断电无法运行清理，JSON 每约一秒 checkpoint，仍可能留下 running 状态。先确认旧记录器不在运行、检查 Action/机器人状态和日志，再显式结束：

```bash
python3 scripts/experiment_log.py finish --run-id "$RUN_ID" \
  --outcome failed --notes '记录器异常退出；真实 Action 终态未知，人工核查后结束记录'
```

这里 failed 表示实验未完整完成，不声称 Action 返回了失败。不要将旧 running 记录自动改成成功。已有 `results/runs/20261025T090837Z_exploratory_t01_bf1826` 在本次修改前已是 running，本次不更改。

### 测试与验收边界

```bash
/usr/bin/python3 scripts/test_experiment.py
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 scripts/test_action.py
```

Action 测试使用 ROS_DOMAIN_ID=187 的模拟服务器和临时结果目录，验证协议及异常，不运行 Gazebo、不向项目 summary.csv 写入模拟结果；187 需留给测试，不应运行真实设备。模拟成功不能作为真实导航成功。本次没有执行新的真实导航、固定目标集或正式基线评测。真实验收仍需在已初始化的仿真中执行上面的单目标命令，核对生成的 JSON 和唯一 CSV 行。
