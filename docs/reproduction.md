# 复现与启动

本指南介绍在已有 ROS 2 Jazzy 和 TurtleBot 4 Simulator 的环境中，启动 warehouse 仿真并完成一次导航。无需为了运行本项目重新安装 ROS、重建工作空间或修改导航算法。

[返回首页](../README.md) · [目标集](goal_set.md) · [实验记录](experiment_logging.md) · [环境排障](troubleshooting.md)

## 环境要求

| 组件 | 已验证配置 |
| --- | --- |
| 操作系统 | Ubuntu 24.04.4 LTS / WSL2 |
| ROS 2 | Jazzy；ros-base 0.11.0 |
| Gazebo Sim | Harmonic 8.15.0 |
| TurtleBot 4 Simulator | 2.0.2 |
| Nav2 bringup | 1.3.13 |
| iRobot Create description | 3.0.4 |
| Python | 系统 `/usr/bin/python3`，3.12.3 |
| 图形 | NVIDIA RTX 3060 Laptop GPU / Mesa D3D12 |

这些版本是已验证环境的参考，不是对任意安装组合的兼容承诺。本仓库提供脚本和说明，不包含 ROS 2、Gazebo、Nav2 的完整安装器。下文约定仓库位于 `~/turtlebot4_ws/src/turtlebot4-navlab`。

在 **WSL Ubuntu 终端**中检查依赖：

```bash
source /opt/ros/jazzy/setup.bash
echo "$ROS_DISTRO"
gz sim --version
/usr/bin/python3 --version
ros2 pkg prefix turtlebot4_gz_bringup
ros2 pkg prefix nav2_bringup
```

预期能看到 Jazzy、Gazebo 8.x、系统 Python 3.12，以及两个包的安装路径。若某条命令不存在，先完成对应依赖的安装或环境加载，再继续。

## 首次使用：检查传感器配置

启动器要求传感器使用 Ogre 2。先进行只读检查：

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
/usr/bin/python3 scripts/manage_ogre2.py status
```

若已经是 `ogre2`，直接进入下一步。若仍是 `ogre`，请先阅读 [Ogre 2 补丁说明](troubleshooting.md#ogre-2-补丁管理)：该兼容补丁会修改 `/opt/ros/jazzy` 中的一处传感器配置，并提供备份和回滚。确认适用后才需要运行 `apply`；正常启动不会自动修改系统文件。

## 1. 启动仿真

先在旧仿真终端按 `Ctrl+C` 退出，避免同时启动多套同名节点。然后在终端 A 运行：

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
./scripts/start_navigation.sh
```

如果提示没有执行权限，先运行 `chmod +x scripts/start_navigation.sh`。

脚本会加载 ROS 和已有 workspace overlay，检查依赖与 Ogre 2 配置，启动 **warehouse、Gazebo、AMCL、Nav2 和 RViz**。首次加载场景可能需要等待。

终端会显示启动日志路径，默认保存在 `~/turtlebot4_ws/log/navlab/`，不进入项目版本库。保持终端 A 运行。

## 2. 确认初始定位

起点是固定的，不需要手工设置。一键脚本通过 `config/localization.yaml` 把 AMCL 的初始位姿设为地图原点 `S0 = (0, 0, 0)`，同时把 Gazebo 的出生位姿固定在世界原点，两者一致。

**不要使用 RViz 的 2D Pose Estimate。** 它会覆盖参数里的固定起点，使该次运行与其它运行不可比。那个工具只适合临时调试，不属于本流程。

另开终端 B 验证定位已建立：

```bash
source /opt/ros/jazzy/setup.bash
ros2 run tf2_ros tf2_echo map base_link
```

应持续输出 `Translation: [0.000, 0.000, 0.000]`、`RPY: [0, -0, 0]`，按 `Ctrl+C` 结束。

这个数字是初始猜测自动生效的结果，**不代表定位精度已经被验证**：机器人没有移动时 AMCL 不做观测更新，位姿就停在种子上。定位是否与地图一致，要看 RViz 里 LaserScan 与地图墙体的贴合程度。起点数值的来源和验证方法见 `config/navigation_goals.yaml` 的文件头注释。

## 3. 发送第一个导航目标

在 RViz 点击 **Nav2 Goal**，选择机器人附近、远离墙壁和货架的可通行空旷位置，拖动指定到达后的朝向。

机器人应开始移动，到达后显示成功状态。首次使用建议先验证一个近距离目标，再尝试更远的位置。此方式使用 RViz 发目标，当前不会自动生成完整实验记录；需要记录时，见下一节。

## 4. 按需记录结果

| 操作方式 | 如何记录 |
| --- | --- |
| 在 RViz 中点击 Nav2 Goal | 目前使用 `start` / `finish` 手工登记 |
| 用命令发送一个地图坐标目标 | 使用 `navigate` 自动发送并采集，结束后自动写入结果 |

具体命令见 [实验记录说明](experiment_logging.md)。当前没有后台监听 RViz Goal 的自动记录功能，不要同时用两个入口发送目标。

## 5. 结束运行

有任务正在执行时，先取消目标；若使用 `navigate`，可在它的终端按 `Ctrl+C` 请求取消并等待记录结束。随后在终端 A 按 `Ctrl+C` 退出整套仿真。

下一次运行重复"启动 → 验证定位 → 发目标"即可，没有手工定位步骤，也不需要每次重新构建或重新应用补丁。

## 无法导航时先检查什么

另开终端 B：

```bash
source /opt/ros/jazzy/setup.bash
if [ -f ~/turtlebot4_ws/install/setup.bash ]; then
  source ~/turtlebot4_ws/install/setup.bash
fi
ros2 lifecycle get /amcl
ros2 lifecycle get /bt_navigator
ros2 control list_controllers -c /controller_manager
ros2 run tf2_ros tf2_echo map base_link
```

AMCL 和 bt_navigator 应为 active，驱动控制器应已启动。`tf2_echo` 会持续输出，可按 `Ctrl+C` 结束；若 `map` 坐标系始终不存在，说明 AMCL 没有拿到初始位姿，先回到第 2 节核对 `config/localization.yaml`。

TF 的主要关系是 `map → odom → base_link`：AMCL 提供地图定位关系，里程计提供机器人相对运动。图形、雷达、Transport、控制器或 Python 问题的进一步排查见 [环境排障](troubleshooting.md)。
