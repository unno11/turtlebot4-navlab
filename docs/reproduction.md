# 复现与启动（ROS 2 Jazzy / Gazebo Harmonic / TurtleBot 4）

## 已验证配置

- Ubuntu 24.04.4 LTS / WSL2；ROS 2 Jazzy；Gazebo Harmonic 8.15.0。
- `ros-jazzy-nav2-bringup` 1.3.13；`ros-jazzy-turtlebot4-simulator` 2.0.2；`ros-jazzy-irobot-create-description` 3.0.4。
- RTX 3060 Laptop GPU / Mesa D3D12；Gazebo warehouse。
- 问题证据：修复前 `/scan` 640/640 个点都是最小值 0.164 m。
- 已记录单次 Nav2 `Reached`：剩余 0.03 m、RViz 耗时 19 s、恢复 1 次；尚非统计基线。

## 复现经过与证据边界（2026-10-25 核查）

以下按可恢复的操作顺序叙述。Shell history 保存了命令但没有逐条时间或输出，因此不能据此补造精确时间线。版本是本次机器快照，不代表所有历史运行均使用相同 Debian 修订号。

| 组件 | 本机核验版本 |
| --- | --- |
| Ubuntu / ROS 2 | 24.04.4 LTS / Jazzy；`ros-jazzy-ros-base` 0.11.0-1noble.20260412.071950 |
| Gazebo Sim | Harmonic，8.15.0 |
| TurtleBot 4 Simulator | 2.0.2-1noble.20261006.050425 |
| Nav2 bringup | 1.3.13-1noble.20261006.042503 |
| 系统 Python | `/usr/bin/python3`，3.12.3 |

ROS 2 是一组包，没有一个适用于所有包的统一补丁版本。可重新采集：

```bash
cat /etc/os-release
uname -r
source /opt/ros/jazzy/setup.bash
echo "$ROS_DISTRO"
gz sim --version
dpkg-query -W ros-jazzy-ros-base ros-jazzy-nav2-bringup ros-jazzy-turtlebot4-simulator
/usr/bin/python3 --version
```

### 1. WSL2 环境准备和图形检查（人工）

历史命令先检查 Ubuntu、内核、内存、磁盘、DISPLAY、WAYLAND_DISPLAY 和 `/dev/dxg`，然后检查 ROS demo、RViz、Gazebo 和已安装包。这些是既有安装的历史记录；本次无需重装，也不创建工作空间。

```bash
uname -r
free -h
df -h /
printf '%s\n' "$DISPLAY" "$WAYLAND_DISPLAY"
ls -l /dev/dxg
glxinfo -B
```

本次普通 shell 的实际输出仍是 `Device: llvmpipe (LLVM 20.1.2, 256 bits)`、`Accelerated: no`。仅安装 NVIDIA 驱动不能证明该终端的 OpenGL 已使用 GPU。切换并验证：

```bash
env -u LIBGL_ALWAYS_SOFTWARE -u LIBGL_ALWAYS_INDIRECT \
  GALLIUM_DRIVER=d3d12 MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA glxinfo -B
```

本次实际输出（节选）：

```text
Vendor: Microsoft Corporation (0xffffffff)
Device: D3D12 (NVIDIA GeForce RTX 3060 Laptop GPU) (0xffffffff)
Version: 25.2.8
Accelerated: yes
```

启动脚本已经设置上述环境变量，以及 `QT_QPA_PLATFORM=xcb`、`LIBGL_DRI3_DISABLE=1`。这些是本机经验配置；不能据此断言历史所有崩溃均由 llvmpipe 导致。

### 2. warehouse、Transport 与控制器排障（人工，启动已自动化）

先运行官方 warehouse，再检查 Gazebo 服务、ROS bridge 和控制器，随后启动定位与导航。历史用过禁用 Nav2/RViz 的分步 launch；目前统一由下面的启动脚本完成。

```bash
gz service -s /gazebo/worlds --reqtype gz.msgs.Empty \
  --reptype gz.msgs.StringMsg_V -r 'unused: true' --timeout 3000
gz topic -l
ros2 topic list
ros2 control list_controllers -c /controller_manager
ros2 service list | grep controller_manager
ros2 param get /controller_manager use_sim_time
```

Transport 服务超时应先区分 server 未启动、场景尚在加载和发现/通信问题；没有保存早期服务响应，具体根因尚未验证，不把网络配置猜测写成结论。本次启动日志能看到 `/world/warehouse/enable_collision` 等服务和 `warehouse_collision`，证明 warehouse 已进入加载流程。日志同时存在 `geometry ... couldn't be created` 警告，不能仅凭警告认定场景完全正常或导航失败由此引起。

历史控制器检查包括 `ldd`/`ldd -r /opt/ros/jazzy/lib/libcontroller_manager.so`，以及对 diagnostic_updater 的定向升级；说明曾排查动态库/包版本问题，但没有原始符号错误输出，ABI 不一致只能列为候选原因。本次不重复升级。较晚的 `navigation_20261025_170823.log` 已出现 `Resource Manager has been successfully initialized. Starting Controller Manager services...`，旧问题不能描述成当前仍然无法启动。现场验收仍应检查 diffdrive_controller 和 joint_state_broadcaster 的 active 状态。

### 3. LiDAR 异常、Collision Monitor 和进展失败（人工诊断）

已有复现记录保存的观测是 `/scan` 640/640 点均为最小值 0.164 m。Shell history 中有使用 SensorDataQoS 的扫描健康检查程序，统计总点数、有限值、最小/中位/最大值和接近最小量程比例；但早期统计的原始输出文件未找到。640 点和 0.164 m 是历史观测，不能伪装成本次重新测量。

`~/turtlebot4_nav.log` 提供了独立故障证据：

```text
[collision_monitor]: Robot to approach for 1.200000 seconds away from collision
[controller_server]: Failed to make progress
```

同一日志中进展失败多次重复。近距离错误扫描可能使 Collision Monitor 持续干预，继而阻碍导航；这是与观测一致的解释，不是对底层 Ogre 驱动缺陷的完整因果证明。未禁用碰撞监控，未修改安全配置或导航算法。

将传感器 `<render_engine>ogre</render_engine>` 改为 `ogre2` 并重启后，已有记录报告首次 Goal 到达；当前补丁脚本、patch 文件和后续日志可以相互核对。修复后的原始扫描分布尚缺失，因此只可写“导航恢复并成功到达”，不能声称已测得修复后全部 640 点正确，或已排除所有其他因素。系统补丁原因、边界及回滚见下节；本次开发不修改 `/opt/ros/jazzy`。

### 4. TF、AMCL 初始化与首次到达（人工）

定位关系为 `map → odom → base_link`：AMCL 根据地图和扫描提供 map→odom，里程计/仿真控制链提供 odom→base_link，robot_state_publisher 等提供机体到传感器的关系。不要为消除警告额外发布固定 map→odom。

```bash
ros2 lifecycle get /amcl
ros2 lifecycle get /bt_navigator
ros2 run tf2_ros tf2_echo map odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_ros tf2_echo map base_link
```

在 RViz 用 `2D Pose Estimate` 指定机器人地图位置和朝向，等待扫描与地图贴合，确认 TF 持续可用后发送 `Nav2 Goal`。未初始化时可能没有 map TF；较晚启动日志确实有 `"map" passed to lookupTransform argument target_frame does not exist`，不能把这种启动期现象都归因于 LiDAR。

首次成功的历史人工观测为 `Reached`、剩余距离 0.03 m、导航耗时 19 s、恢复 1 次。`~/.ros/log/bt_navigator_*.log` 有较早的 `Goal succeeded`；后续 `navigation_20261025_165739.log` 还有：

```text
[controller_server]: Reached the goal!
[bt_navigator]: Goal succeeded
```

这些日志证明有成功事件，但不能仅据这两行还原 19 s、0.03 m、1 次或断言它们就是第一次任务。三项数值沿用已有人工记录；没有完整 trial 和目标协议，不回填 summary.csv 为正式评测。

### 5. 后续工程整理：Colcon Python 冲突与脚本管理

已保存的 `log/build_2026-10-25_16-25-01/turtlebot4_navlab/stderr.log` 明确记录：

```text
ModuleNotFoundError: No module named 'catkin_pkg'
execute_process(/home/tsy/.local/bin/python3.10 ... package_xml_2_cmake.py ...)
```

这是选中了用户 Python 3.10 而非 Jazzy 系统 Python 3.12 的直接证据。history 保存的修复命令为：

```bash
type -a python3
/usr/bin/python3 --version
/usr/bin/python3 -c 'import catkin_pkg; print(catkin_pkg.__file__)'
cd ~/turtlebot4_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select turtlebot4_navlab \
  --executor sequential --cmake-clean-cache \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
source install/setup.bash
ros2 pkg prefix turtlebot4_navlab
```

本次 CMakeCache 显示 `/usr/bin/python3` 和 `v3.12.3`，修复后的构建日志在 `build_2026-10-25_16-31-54/`。这里只记录原有工作空间的定向重建方式，无需每次启动重建。当前证据将此次构建冲突定位于后续工程整理，不能为了叙述把它硬插到首次导航之前。

Git 顺序：`b760d94` 初始化；`024b290` 增加补丁管理和启动器；`36068c9` 清理 Windows 元数据；`212cdd5` 增加实验记录。上述提交是代码整理顺序，不等于全部运行事件的发生顺序。


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

## 全新终端的最小复现（现有安装）

终端 A：先退出旧仿真，再检查补丁并启动。这里的 status 只读，不应用系统补丁。

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
/usr/bin/python3 scripts/manage_ogre2.py status
./scripts/start_navigation.sh
```

终端 B：

```bash
source /opt/ros/jazzy/setup.bash
source ~/turtlebot4_ws/install/setup.bash
ros2 lifecycle get /amcl
ros2 lifecycle get /bt_navigator
ros2 run tf2_ros tf2_echo map base_link
```

人工在 RViz 完成 2D Pose Estimate，确认扫描与地图贴合、TF 连通；然后在 RViz 发送单个 Goal，或按 [自动实验说明](experiment_logging.md#自动执行单个-navigatetopose-任务) 使用 navigate 自动发目标并采集。不要同时使用两个发目标入口。自动入口不要求重新 colcon build。

已自动化：启动前检查、环境变量、官方 launch 与启动日志、补丁状态管理、单目标 Action 采集及结果去重。仍需人工：初始位姿、安全目标选择、扫描与地图核对、异常退出后的机器人状态检查。尚未实现：碰撞真值计数、Ground Truth 路径、可靠 Gazebo RTF、固定目标与正式基线统计。以上不是新的阶段或算法开发。
