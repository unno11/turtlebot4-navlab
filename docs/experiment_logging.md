# 实验记录

本项目提供两种记录方式：**命令发送目标并自动采集**，或 **RViz 发目标后手工登记**。所有方式共用同一套 JSON 和 CSV 格式。

[返回首页](../README.md) · [先启动仿真](reproduction.md) · [结果字段](../results/README.md)

## 选择记录方式

| 你的操作 | 使用方式 | 是否自动采集 |
| --- | --- | --- |
| 已知目标地图坐标，希望自动保存指标 | `navigate` | 是，工具负责发目标并记录 |
| 在 RViz 中点击 Nav2 Goal | `start` → RViz 操作 → `finish` | 否，需要人工确认结果 |

当前工具还不能在后台监听 RViz Goal 并自动记录。使用 `navigate` 时不要另发 RViz Goal，也无需再运行 `start` 或 `finish`。

## 自动执行单个 NavigateToPose 任务

先按 [启动指南](reproduction.md) 启动仿真。一键脚本已经把 AMCL 的初始位姿固定在地图原点 `S0 = (0, 0, 0)`，所以**不要**在 RViz 里点 `2D Pose Estimate`——那会覆盖参数里的固定起点，使不同试验的起点不再一致，数据也就不可比了。

启动完成后另开 WSL 终端：

```bash
source /opt/ros/jazzy/setup.bash
if [ -f ~/turtlebot4_ws/install/setup.bash ]; then
  source ~/turtlebot4_ws/install/setup.bash
fi
cd ~/turtlebot4_ws/src/turtlebot4-navlab
```

目标 `x、y` 是 **map 坐标系中的绝对位置**，单位米；`yaw` 是到达后的朝向，单位弧度，不是相对机器人前进的距离。请选择可通行区域中的位置。

如果不知道坐标，可先运行：

```bash
ros2 topic echo /clicked_point --once
```

再在 RViz 用 **Publish Point** 点击目标位置，读取输出的 `point.x`、`point.y`。此操作只取坐标，不发送导航目标。`yaw=0` 表示朝向地图正 X 方向。

运行下面一行后，终端会等待输入；输入选好的三个数 `x y yaw`，以空格分隔并回车：

```bash
read -r GOAL_X GOAL_Y GOAL_YAW
```

然后发送目标并开始记录：

```bash
/usr/bin/python3 scripts/experiment_log.py navigate \
  --goal-id exploratory --trial 1 \
  --x "$GOAL_X" --y "$GOAL_Y" --yaw "$GOAL_YAW" \
  --timeout 300 --stale-timeout 30
```

结束后程序输出记录位置，自动保存 `results/runs/<run_id>/run.json`，并向本地 `results/summary.csv` 写入唯一一行。`goal-id` 是便于识别的标签；`trial` 是同一目标的试验序号，可按实际运行修改。

### 常用参数

| 参数 | 默认值 / 作用 |
| --- | --- |
| `--timeout` | 300 秒，整个任务的墙钟上限，包含等待服务 |
| `--stale-timeout` | 30 秒，仿真时钟不前进或 odom 中断的上限 |
| `--cancel-grace` | 5 秒，请求取消后等待确认的宽限 |
| `--action` / `--odom` / `--frame` | `/navigate_to_pose` / `/odom` / `map` |
| `--launch-log` | 可选，关联启动终端输出的日志绝对路径 |

超时使用现实时间，暂停仿真也可能触发超时。仿真时钟 topic 当前固定为 `/clock`。成功退出码为 0，其余为 1。

## 结果分类与作废规则

这三条规则必须在跑第一组数据**之前**写定，不能事后按结果归类，否则成功率失去意义。

| 分类 | 判据 | 是否计入成功率 |
| --- | --- | --- |
| `succeeded` | Action 返回 SUCCEEDED（status 4） | 计入成功 |
| `failed` | Action 返回 ABORTED（status 6） | 计入失败 |
| `invalid` | 记录存在但没有形成导航结果：`termination_reason` 不是 `action_result`（墙钟超时、数据流中断、ROS 上下文丢失），或 `action_status` 不是 4/6 | **不计入**，单独统计 |
| `unfinished` | 记录器没有收尾（`state` 不是 `finished`） | 不计入，可重跑 |

判据只看**动作有没有返回最终状态**，不看 RTF。这套规则的实现集中在 `scripts/run_record.py`，汇总脚本（`summarize_results.py`、`compare_arms.py`）与批量脚本（`run_batch.sh` 的 `already_done`）共用同一份判定 —— 早先两边各自判断，导致汇总认为"无效"的记录被批量脚本当成"已完成"而跳过。

分类只回答"这一次导航有没有形成结果"。一次运行能不能用来比较优劣是另一个问题，取决于 RTF、指令时效等条件是否受控，见 [分类正确不等于实验可用](#分类正确不等于实验可用)。两者不共用判据，也不同步修改。

早期版本把 `failed` 写成"ABORTED 且 `rtf_estimate` ≥ 0.5"，那是把宿主速度和导航结果混在一起。RTF 低会让墙钟超时和 `cmd_vel` 时间戳过期更容易发生，但它不决定**动作最终是失败，还是被工具打断**。需要区分的是终止原因，不是速度。

`invalid` 只允许用于**与导航能力无关的终止**：墙钟超时、仿真时钟或里程计停更、挂钟与仿真时钟不一致导致的中断。判据必须能在日志或指标里指出来，不能凭印象。

作废的试验**不删除、不改编号**。`trial` 序号继续往后走，`notes` 按「现象；证据；结论」三段写，便于日后复查：

```
host_budget_exhausted; wall_timeout at rtf_estimate=0.19, remaining 1.06 m; not a navigation result
```

报告成功率时同时给出三个数：`succeeded` / `failed` / `invalid_host`，分母只含前两者。

## 仿真速度门禁（RTF）

RTF = 仿真时间推进速度 ÷ 现实时间。RTF 过低会提前触发墙钟超时，也会让 `cmd_vel` 时间戳过期被底盘丢弃，直接污染数据。

每次试验前测一次：

```bash
ros2 topic echo --once /clock --field clock.sec
sleep 10
ros2 topic echo --once /clock --field clock.sec
```

两个读数之差 ÷ 10 就是 RTF。

| RTF | 处理 |
| --- | --- |
| ≥ 0.7 | 正常，`--timeout` 用 300 |
| 0.5–0.7 | 可用，`--timeout` 提到 600，并在这批数据里记录 RTF |
| < 0.5 | **不跑试验**，先降负载（见下） |

### 单次失败不等于算法失败

在这个宿主上（RTF 0.19–0.30），单次运行的成败重复性很低。三个控制器在 G05 上的同一份配置，批次里两次中止、复跑里两次通过，参数没有任何变化 —— 详见 [局部控制器对比](controller_comparison.md)。

因此：

- 一条 `failed` 记录只是"这一次失败了"，不是"这个配置不行"。
- 拿失败记录做结论前，对同一目标至少复跑 1 次；两次都失败才值得写进文档。
- 讨论成功率时把重复次数一起写出来。`1/1` 与 `3/3` 在文档里的分量不同。

### 已记录批次没有满足这条门禁

基线批次与控制器对比批次的 `rtf_estimate` 实测为 **0.19–0.30**，全部落在"不跑试验"区间。这些数据保留下来了，但代价必须一起写明，否则数字会显得比实际更干净：

- **与墙钟无关，但不等于不受影响**：`nav_time_sim_s`、剩余距离、恢复次数取自仿真时间与 Nav2 反馈，跟宿主跑得多快无关；然而被丢弃的速度指令会改变实际轨迹，也就改变了仿真耗时和恢复次数。这些指标只在条件相同的运行之间可比。
- **受影响**：墙钟耗时不可跨批次或跨机器比较。低 RTF 下 diffdrive 会丢弃过期速度指令，同一台机器上 G05 的三次运行分别出现 **41 / 36 / 82** 条 `Ignoring the received message ... older than` 告警，说明有部分 `cmd_vel` 没有生效。
- **因此不能下的结论**：把"某个控制器在窄通道下失败"归因于控制律。RPP 与 Graceful 在批次里中止、在同一配置的复跑里全部通过，两次运行的指令丢弃数也相差几倍；现有证据无法把控制律差异与运行条件波动分开，见 [局部控制器对比](controller_comparison.md)。
- **要消除这个疑点**：在 RTF ≥ 0.5 的宿主上重跑，或对每个目标做多次重复，让运行条件的影响被重复平均掉。

### 分类正确不等于实验可用

把 ABORTED 记为失败是对的，低 RTF 也不是排除一条记录的理由 —— 这是两件不同的事：

- **分类**回答"这一次导航有没有形成结果"，只看动作有没有返回最终状态。与宿主速度无关，也不该用它来调整。
- **质量**回答"这个结果能不能用来比较优劣"，取决于运行条件是否受控。

低 RTF 的批次在第二问上不合格：耗时记的确实是仿真时间，但被丢弃的指令可能改变轨迹，进而改变仿真耗时、恢复次数甚至成败。用它做控制器优劣的定量结论，等于把两个来源混在一起，而且分不出各占多少。

`summarize_results.py` 会在表尾打印实际记录的 RTF 范围，避免这个前提被忘掉。

降低 RTF 的手段，按收益排序：关闭 Gazebo 的射线可视化（一键脚本已设 `visualize_rays:=false`，它把雷达的每条射线每帧重画一遍，对物理和导航没有贡献）、关闭 RViz、确认 Gazebo 在使用 GPU 而非软件渲染。

`summary.csv` 的 `gazebo_rtf` 保持空值——它没有可靠的自动来源。需要参考值时用下面的估算，并明确标注是估算：

```
rtf_estimate = nav_time_sim_s / duration_wall_s
```

分母包含等待接受和取消宽限，因此略低于真实 RTF。它只用于判断宿主是否处于可用档位，不参与单次结果的分类，也不要写进性能对比。

## 在 RViz 导航时手工登记

发送目标前创建记录：

```bash
python3 scripts/experiment_log.py start --goal-id exploratory --trial 1
```

保存输出的 `RUN_ID`，再在 RViz 发目标。任务结束后，将它填入变量，并按实际结果选择 `succeeded`、`failed` 或 `canceled`：

```bash
RUN_ID='替换为刚才输出的ID'
python3 scripts/experiment_log.py finish \
  --run-id "$RUN_ID" --outcome succeeded \
  --notes '人工确认导航到达'
```

这里只登记已确认的结果。已测得的指标可按 `finish --help` 添加；未测得的指标不填，不把零当成未知。

## 查看和保存记录

```bash
python3 scripts/experiment_log.py list
head -n 5 results/summary.csv
```

尚未结束的 run 不会进入汇总。每次运行的数据均只保留在本地，Git 只跟踪说明和无数据行的 `summary.example.csv`。启动日志保存在 workspace 的 `log/navlab/` 下。请自行备份重要数据，不要强制把原始记录加入 Git。

## 自动指标的含义

自动记录 Action 最终状态、最后收到的导航耗时／剩余距离／恢复次数、真实墙钟耗时、odom 路径估计、Git Commit、目标位姿和起止时间。完整字段见 [结果字段说明](../results/README.md#字段说明)。

- 反馈可能早于最终状态，因此剩余距离和导航耗时是最后收到的样本。
- 路径来自里程计，不是 Gazebo Ground Truth；丢包、漂移和位置跳变会影响估计。
- 路径长度只有和 Nav2 规划的路线长度对比才有意义。明显超出（例如 +30% 以上）说明发生了绕行或恢复行为，不能直接当作"走了多远"。
- 碰撞次数和 Gazebo RTF 没有可靠数据源，保持 JSON `null`、CSV 空值；RTF 参考值按上一节 `rtf_estimate` 估算，不进 CSV。
- 超时或数据流中断属于实验失败，不能据此断定 Action 返回 aborted，或 Gazebo 已崩溃。RTF 充足时出现 status 5 也要先查原因，不要默认归为宿主问题。

## 取消与中断恢复

自动任务中按 `Ctrl+C` 会请求取消。只有收到服务器的 canceled 状态才确认取消；如果未收到确认，需检查机器人是否仍在执行。ROS 上下文退出后，记录器无法再发送取消请求。

JSON 已结束、CSV 缺行时，可重新同步；重复执行不会增加同一 run 的行数：

```bash
python3 scripts/experiment_log.py recover --run-id "$RUN_ID"
```

SIGKILL 或断电可能留下 running 记录。先确认旧记录器已退出，核查机器人状态和日志，再显式标记实验未完整完成：

```bash
python3 scripts/experiment_log.py finish --run-id "$RUN_ID" \
  --outcome failed --notes '异常中断，Action真实终态未知，已人工核查'
```

`recover` 不推断 running 任务成功。未提供指标的 `finish` 会保留 checkpoint 已采集的值。

## 开发者测试

```bash
/usr/bin/python3 scripts/test_experiment.py
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 scripts/test_action.py
```

Action 测试使用独立 ROS_DOMAIN_ID=187 和模拟服务器，结果写入临时目录。测试期间不要在该 Domain 连接真实设备；模拟成功仅验证记录流程，不代表真实导航成功。
