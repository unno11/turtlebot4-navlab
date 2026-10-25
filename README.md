# TurtleBot 4 NavLab

基于 ROS 2 Jazzy、Gazebo Harmonic 和 TurtleBot 4 的室内移动机器人导航项目。使用官方 warehouse 场景，支持 AMCL 定位、Nav2 导航，以及单目标任务的自动结果记录。

## 从这里开始

1. 按 [复现与启动指南](docs/reproduction.md) 检查环境并启动仿真。
2. 在 RViz 设置初始位姿，发送第一个导航目标。
3. 需要保存结果时，阅读 [实验记录说明](docs/experiment_logging.md)。

已配置过本项目的机器，可在 WSL 终端启动：

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
./scripts/start_navigation.sh
```

等待 Gazebo 和 RViz 加载后，在 RViz 使用 **2D Pose Estimate** 完成定位，再使用 **Nav2 Goal** 选择地图中的空旷位置。初次使用请先阅读指南中的环境和传感器配置要求。

## 文档导航

| 文档 | 适合什么时候阅读 |
| --- | --- |
| [复现与启动](docs/reproduction.md) | 第一次运行、确认环境、设置初始位姿、发送目标和退出仿真 |
| [实验记录](docs/experiment_logging.md) | 自动记录一个目标任务，或手工登记 RViz 导航结果 |
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
- [ ] Reproducible baseline evaluation
- [ ] Custom behavior tree plugins
- [ ] Robust LiDAR perception
- [ ] Dynamic obstacle avoidance experiments
- [ ] DDS performance evaluation

实验工具目前支持“发送单个目标并自动采集”和“手工登记”两种方式。后台监听 RViz Goal 的自动记录尚未实现。

## Baseline

已验证单次导航到达。固定目标集、重复试验和正式统计协议尚未建立，因此不将单次到达作为统计基线。每次运行的数据仅保留在本地，不作为项目文档或版本库内容。

## Upstream Projects

- turtlebot/turtlebot4_simulator
- ros-navigation/navigation2
