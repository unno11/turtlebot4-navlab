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

先按 [启动指南](reproduction.md) 运行仿真，在 RViz 完成 **2D Pose Estimate** 并确认扫描与地图贴合。然后另开 WSL 终端：

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
- 碰撞次数和 Gazebo RTF 没有可靠数据源，保持 JSON `null`、CSV 空值。
- 超时或数据流中断属于实验失败，不能据此断定 Action 返回 aborted，或 Gazebo 已崩溃。

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
