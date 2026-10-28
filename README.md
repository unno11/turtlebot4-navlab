# TurtleBot 4 NavLab

ROS 2 Jazzy · Gazebo Harmonic · TurtleBot 4 · Nav2

在官方 warehouse 场景里，用固定的起点、固定的 8 个目标、可重复的批量流程，把 Nav2 的导航表现量化下来 —— 不是"跑通了一次导航"，而是 24 次重复试验、24 次成功、每次都能从零复现。

![NavLab 导航演示](docs/media/navlab-demo.gif)

*RViz 中的一次导航过程（约 6 分钟实时，24 倍速压缩）。红色是 Nav2 规划的全局路径，左下角是实时状态：剩余距离、已用时间、恢复次数。*

**结果一览**：8 个目标 × 3 次 = 24 次，成功率 100%，单次导航 29–205 s（仿真时间）。完整的指标定义与逐目标结果见 [官方基线结果](docs/baseline.md)。

**30 秒复现**：

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
./scripts/start_navigation.sh                    # Gazebo + Nav2 + AMCL，起点自动固定为 S0
TRIALS=3 ./scripts/run_batch.sh                  # 8 个目标 x 3 次，逐步重启、自检、记录
/usr/bin/python3 scripts/summarize_results.py    # 生成结果表
```

起点由启动脚本与 `config/localization.yaml` 固定，**不需要也不应该使用 RViz 的 2D Pose Estimate**。初次运行的环境要求见 [复现与启动指南](docs/reproduction.md)。

## 三个具体问题

这个项目不只是把官方仿真跑起来。中间有三处必须自己判断的地方，也是我认为最值得看的部分。

**1. 起点到底在哪？**

官方启动脚本把机器人放在 Gazebo 世界原点，而 Nav2 需要的是 `map` 坐标系下的起点。早先用手在 RViz 里拖 2D Pose Estimate，得到 `(-0.094, -0.122, -3.122)` —— 既不可复现，也无法判断对错。

改用可验证的方法：取一帧 `/scan`，沿 URDF 链条（`base_link → shell_link → rplidar_link`）变换到车体系，再与 `warehouse.pgm` 的距离变换做拟合。`(0, 0, 0)` 的平均残差是 **0.012 m**，而手拖的那个值残差是 **3.14 m** —— 差了将近一个车身，yaw 也整整反了 180°。

现在起点写在 `config/localization.yaml` 的 `initial_pose` 里，每次启动自动注入 AMCL，全程无需手工操作。

**2. 目标该有多难？**

凭坐标"看起来远"不等于路线难。8 个目标全部用 Nav2 的规划器实际规划一遍，记录路径长度、累计转角、转角密度和最窄处宽度，再按这些数字分成 simple / turning / narrow / long 四类，而不是按目标坐标拍脑袋。

这套判据固化在 `scripts/check_paths.py` 里：每次跑实验之前先自检，任何一项偏离基线就拒绝开始，避免环境漂移悄悄污染一整批数据。

**3. 24 次试验怎么保证可比？**

每次试验之间必须整套仿真重启 —— 只有这样，Gazebo 的出生位姿和 AMCL 的初始位姿才回到同一个状态，起点才真的是同一个起点。手工点 24 次不可靠，所以写了 `scripts/run_batch.sh`：逐条启动、等待 Nav2 就绪、跑环境自检、发送目标、记录结果、关闭仿真、进入下一条；中断后重跑会自动跳过已完成的试验。

统计口径也不含糊：被墙钟超时打断的记录不算"导航失败"，它根本没形成导航结果。判定规则写在 [实验记录](docs/experiment_logging.md) 里，避免把工具问题算成算法问题。

## 文档导航

| 文档 | 适合什么时候阅读 |
| --- | --- |
| [复现与启动](docs/reproduction.md) | 第一次运行、确认环境、确认初始定位、发送目标和退出仿真 |
| [目标集与难度定义](docs/goal_set.md) | 了解 8 个导航目标、难度判据，以及如何用 Nav2 规划器复核 |
| [官方基线结果](docs/baseline.md) | 查看基线的场景条件、结果表、指标口径与复跑方式 |
| [实验记录](docs/experiment_logging.md) | 自动记录一个目标任务、结果分类规则、仿真速度门禁，或手工登记 RViz 导航结果 |
| [结果目录](results/README.md) | 查看输出位置、字段含义与本地数据管理方式 |
| [环境排障](docs/troubleshooting.md) | 出现图形、雷达、TF、控制器或 Python 构建问题时 |

## Environment

- Ubuntu 24.04 / WSL2
- ROS 2 Jazzy
- Gazebo Harmonic
- TurtleBot 4 Simulator
- Nav2

已验证版本和检查命令见 [环境要求](docs/reproduction.md#环境要求)。启动脚本包含 NVIDIA D3D12 设置，主要面向该 WSL2 环境；其他显卡和原生 Linux 环境需要单独验证。

## Current Status

- [x] TurtleBot 4 warehouse simulation
- [x] Keyboard teleoperation
- [x] AMCL localization and Nav2 navigation
- [x] Initial navigation goal reached
- [x] Reproducible baseline evaluation (8 goals x 3 trials, all succeeded)
- [ ] Custom behavior tree plugins
- [ ] Robust LiDAR perception
- [ ] Dynamic obstacle avoidance experiments
- [ ] DDS performance evaluation

实验工具目前支持“发送单个目标并自动采集”和“手工登记”两种方式。后台监听 RViz Goal 的自动记录尚未实现。

## Baseline

官方基线的完整结果见 [官方基线结果](docs/baseline.md)：8 个目标各 3 次，共 24 次，全部成功，并给出每个目标的导航耗时与恢复次数。

起点固定 S0、目标集难度由 Nav2 规划器逐条复核（见 [目标集说明](docs/goal_set.md)）；结果分类规则与仿真速度门禁写在 [实验记录](docs/experiment_logging.md)。

每次运行的原始数据仅保留在本地，不作为项目文档或版本库内容。

## Upstream Projects

- turtlebot/turtlebot4_simulator
- ros-navigation/navigation2
