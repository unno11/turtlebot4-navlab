# 复现与启动（ROS 2 Jazzy / Gazebo Harmonic / TurtleBot 4）

## 已验证配置

- Ubuntu 24.04.4 LTS / WSL2；ROS 2 Jazzy；Gazebo Harmonic 8.15.0。
- `ros-jazzy-nav2-bringup` 1.3.13；`ros-jazzy-turtlebot4-simulator` 2.0.2；`ros-jazzy-irobot-create-description` 3.0.4。
- RTX 3060 Laptop GPU / Mesa D3D12；Gazebo warehouse。
- 问题证据：修复前 `/scan` 640/640 个点都是最小值 0.164 m。
- 已记录单次 Nav2 `Reached`：剩余 0.03 m、RViz 耗时 19 s、恢复 1 次；尚非统计基线。

## 传感器渲染补丁

> 本阶段为可重复、可校验、可回滚的**临时系统文件补丁**。它并未实现纯 Overlay。正式产品化前应迁移到自己管理的 ROS 2 包或可覆写安装路径。

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
python3 scripts/manage_ogre2.py status
sudo python3 scripts/manage_ogre2.py apply
python3 scripts/manage_ogre2.py status
```

- 仅允许文件出现一次 `<render_engine>ogre</render_engine>` 或一次 `<render_engine>ogre2</render_engine>`。
- 如果已经是 `ogre2`，`apply` 不会重复修改。
- 对本工具第一次应用前的文件会在 `/opt/ros/jazzy/share/irobot_create_description/urdf/create3.urdf.xacro.navlab-ogre1.bak` 创建备份。
- 若此前已**手动**改成 `ogre2`，脚本识别为已应用，但不能补造“原始文件”的备份。
- 回滚：`sudo python3 scripts/manage_ogre2.py revert`。若存在本工具备份，只有差异严格限于这一行才会恢复；否则只恢复这一行。恢复后需重启 Gazebo。
- `patches/create3-ogre2.patch` 是最初的补丁记录；`manage_ogre2.py` 提供当前的状态检查和应用流程。

## 一键启动

先退出旧的 Gazebo、RViz 和键盘遥控进程（各自终端按 `Ctrl+C`），不要叠加启动同名节点。

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
chmod +x scripts/start_navigation.sh
./scripts/start_navigation.sh
```

启动脚本在检测 ROS 环境、Gazebo、TurtleBot 4 包和 Ogre2 设置后，启动 `warehouse`、Nav2、AMCL 和 RViz，并将终端日志存入 `~/turtlebot4_ws/log/navlab/`。它不自动修改 `/opt` 文件，也不自动重启 WSL。

## 验证

```bash
source /opt/ros/jazzy/setup.bash
ros2 lifecycle get /amcl
ros2 lifecycle get /bt_navigator
ros2 control list_controllers -c /controller_manager
```

初始位姿需要在 RViz 点击 `2D Pose Estimate`，确认激光扫描贴合地图后再发 `Nav2 Goal`。首次完成的状态为 `Reached`，尚需额外测量修复后的雷达测距分布和重复导航成功率。

## 风险边界

- 修改 `/opt/ros/jazzy` 可能被 APT 更新覆盖；每次升级后先运行 `status`。
- 启动时带的 WSL 渲染变量是该设备上的经验设置，不代表其他 Linux 计算机都应使用。
- 若 Ogre2 崩溃或出现异常，请保留日志并回滚；不要禁用 Collision Monitor 或无依据地增加速度指令超时阈值。
