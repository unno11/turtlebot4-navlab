# 环境排障与复现依据

正常使用请先阅读 [启动指南](reproduction.md)。本页集中保存环境兼容问题、补丁管理方法和复现依据，不是每次启动都要执行的步骤，也不存放逐次实验结果。

[返回首页](../README.md) · [实验记录](experiment_logging.md)

## 按现象查找

| 现象 | 对应内容 |
| --- | --- |
| 渲染使用 llvmpipe、图形性能异常 | 下文 WSL2 环境和图形检查 |
| warehouse 未加载或控制器未启动 | 下文 Transport 与控制器排障 |
| 扫描集中在最小距离、导航无进展 | 下文 LiDAR 异常与 Ogre 2 补丁 |
| 缺少 map TF、定位不正确 | 下文 TF 与 AMCL 初始化 |
| Colcon 找到错误 Python 或缺 catkin_pkg | 下文 Python 环境冲突 |

## Ogre 2 补丁管理

> 此方案为可重复、可校验、可回滚的**临时系统文件补丁**。它并未实现纯 Overlay。正式产品化前应迁移到自己管理的 ROS 2 包或可覆写安装路径。

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


## 复现经过与证据边界（2026-10-25 核查）

以下按可恢复的操作顺序叙述。Shell history 保存了命令但没有逐条时间或输出，因此不能据此补造精确时间线。版本来自 2026-10-25 的机器快照，不代表所有历史运行均使用相同 Debian 修订号。

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

历史命令先检查 Ubuntu、内核、内存、磁盘、DISPLAY、WAYLAND_DISPLAY 和 `/dev/dxg`，然后检查 ROS demo、RViz、Gazebo 和已安装包。这些命令用于确认既有安装状态，无需在正常启动时重复安装依赖。

```bash
uname -r
free -h
df -h /
printf '%s\n' "$DISPLAY" "$WAYLAND_DISPLAY"
ls -l /dev/dxg
glxinfo -B
```

2026-10-25 核验时，普通 shell 的输出为 `Device: llvmpipe (LLVM 20.1.2, 256 bits)`、`Accelerated: no`。仅安装 NVIDIA 驱动不能证明该终端的 OpenGL 已使用 GPU。切换并验证：

```bash
env -u LIBGL_ALWAYS_SOFTWARE -u LIBGL_ALWAYS_INDIRECT \
  GALLIUM_DRIVER=d3d12 MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA glxinfo -B
```

相同环境下启用 D3D12 后的输出（节选）：

```text
Vendor: Microsoft Corporation (0xffffffff)
Device: D3D12 (NVIDIA GeForce RTX 3060 Laptop GPU) (0xffffffff)
Version: 25.2.8
Accelerated: yes
```

启动脚本已经设置上述环境变量，以及 `QT_QPA_PLATFORM=xcb`、`LIBGL_DRI3_DISABLE=1`。这些是本机经验配置；不能据此断言历史所有崩溃均由 llvmpipe 导致。

### 2. warehouse、Transport 与控制器排障（人工，启动已自动化）

先运行官方 warehouse，再检查 Gazebo 服务、ROS bridge 和控制器，随后启动定位与导航。历史用过禁用 Nav2/RViz 的分步 launch；目前统一由启动指南中的脚本完成。

```bash
gz service -s /gazebo/worlds --reqtype gz.msgs.Empty \
  --reptype gz.msgs.StringMsg_V -r 'unused: true' --timeout 3000
gz topic -l
ros2 topic list
ros2 control list_controllers -c /controller_manager
ros2 service list | grep controller_manager
ros2 param get /controller_manager use_sim_time
```

Transport 服务超时应先区分 server 未启动、场景尚在加载和发现/通信问题；没有保存早期服务响应，具体根因尚未验证，不把网络配置猜测写成结论。已保存的启动日志能看到 `/world/warehouse/enable_collision` 等服务和 `warehouse_collision`，证明 warehouse 已进入加载流程。日志同时存在 `geometry ... couldn't be created` 警告，不能仅凭警告认定场景完全正常或导航失败由此引起。

历史控制器检查包括 `ldd`/`ldd -r /opt/ros/jazzy/lib/libcontroller_manager.so`，以及对 diagnostic_updater 的定向升级；说明曾排查动态库/包版本问题，但没有原始符号错误输出，ABI 不一致只能列为候选原因。不要在缺少当前错误证据时直接重复升级。较晚的 `navigation_20261025_170823.log` 已出现 `Resource Manager has been successfully initialized. Starting Controller Manager services...`，旧问题不能描述成当前仍然无法启动。现场验收仍应检查 diffdrive_controller 和 joint_state_broadcaster 的 active 状态。

### 3. LiDAR 异常、Collision Monitor 和进展失败（人工诊断）

已有复现记录保存的观测是 `/scan` 640/640 点均为最小值 0.164 m。Shell history 中有使用 SensorDataQoS 的扫描健康检查程序，统计总点数、有限值、最小/中位/最大值和接近最小量程比例；但早期统计的原始输出文件未找到。640 点和 0.164 m 是历史观测，不能当作当前环境的重新测量结果。

`~/turtlebot4_nav.log` 提供了独立故障证据：

```text
[collision_monitor]: Robot to approach for 1.200000 seconds away from collision
[controller_server]: Failed to make progress
```

同一日志中进展失败多次重复。近距离错误扫描可能使 Collision Monitor 持续干预，继而阻碍导航；这是与观测一致的解释，不是对底层 Ogre 驱动缺陷的完整因果证明。未禁用碰撞监控，未修改安全配置或导航算法。

将传感器 `<render_engine>ogre</render_engine>` 改为 `ogre2` 并重启后，已有记录报告首次 Goal 到达；当前补丁脚本、patch 文件和后续日志可以相互核对。修复后的原始扫描分布尚缺失，因此只可写“导航恢复并成功到达”，不能声称已测得修复后全部 640 点正确，或已排除所有其他因素。系统补丁原因、边界及回滚见上文。常规启动只检查状态，不自动修改 `/opt/ros/jazzy`。

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

修复后的 CMakeCache 显示 `/usr/bin/python3` 和 `v3.12.3`，修复后的构建日志在 `build_2026-10-25_16-31-54/`。这里只记录原有工作空间的定向重建方式，无需每次启动重建。现有证据将此次构建冲突定位于首次导航后的工程整理。

Git 顺序：`b760d94` 初始化；`024b290` 增加补丁管理和启动器；`36068c9` 清理 Windows 元数据；`212cdd5` 增加实验记录。上述提交是代码整理顺序，不等于全部运行事件的发生顺序。



## 使用边界

- NVIDIA D3D12 环境变量是已验证设备的经验设置，其他环境需单独检查。
- APT 更新可能覆盖系统补丁，更新后先执行 status。
- 遇到故障保留本地日志，不要通过禁用 Collision Monitor 或无依据地放宽超时来掩盖问题。
- 本页历史输出仅用作排障依据，不作为当前机器状态或可重复基线的证明。
