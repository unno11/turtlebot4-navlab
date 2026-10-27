#!/usr/bin/env bash
# Run official TurtleBot4 Gazebo warehouse + AMCL + Nav2 + RViz with validated WSL graphics env.
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE="$(cd -- "$REPO_ROOT/../.." && pwd)" # repo at ~/turtlebot4_ws/src/turtlebot4-navlab

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo '错误：未找到 ROS 2 Jazzy，请先安装或调整 ROS_DISTRO。' >&2
  exit 1
fi
# ROS setup scripts are not guaranteed to be compatible with `set -u`.
source /opt/ros/jazzy/setup.bash
if [[ -f "$WORKSPACE/install/setup.bash" ]]; then
  source "$WORKSPACE/install/setup.bash"
fi

for cmd in ros2 gz python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "错误：命令不可用：$cmd" >&2
    exit 1
  fi
done
if ! ros2 pkg prefix turtlebot4_gz_bringup >/dev/null 2>&1; then
  echo '错误：找不到 turtlebot4_gz_bringup ROS 包。' >&2
  exit 1
fi
if ! python3 "$SCRIPT_DIR/manage_ogre2.py" status; then
  echo '错误：传感器配置检查失败，取消启动。' >&2
  exit 1
fi
TARGET='/opt/ros/jazzy/share/irobot_create_description/urdf/create3.urdf.xacro'
if ! grep -Fq '<render_engine>ogre2</render_engine>' "$TARGET"; then
  echo "错误：当前传感器不是 Ogre2。请先执行：sudo python3 scripts/manage_ogre2.py apply" >&2
  exit 1
fi

unset LIBGL_ALWAYS_SOFTWARE LIBGL_ALWAYS_INDIRECT
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export QT_QPA_PLATFORM=xcb
export LIBGL_DRI3_DISABLE=1

# Logs live OUTSIDE Git repo; avoids accidentally committing large logs.
LOG_DIR="$HOME/turtlebot4_ws/log/navlab"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/navigation_$(date +'%Y%m%d_%H%M%S').log"
LOCALIZATION_PARAMS="$REPO_ROOT/config/localization.yaml"
if [[ ! -f "$LOCALIZATION_PARAMS" ]]; then
  echo "错误：缺少 $LOCALIZATION_PARAMS（固定起点 S0 的 AMCL 初始位姿）。" >&2
  exit 1
fi
# RViz is a pure subscriber: it does not change navigation behaviour, sensing or any
# recorded metric, but it costs a large share of the simulation real-time factor on
# this machine. Keep it on while debugging, off for experiment runs:
#   RVIZ=false ./scripts/start_navigation.sh
RVIZ="${RVIZ:-true}"
if [[ "$RVIZ" != "true" && "$RVIZ" != "false" ]]; then
  echo "错误：RVIZ 只能取 true 或 false（当前：$RVIZ）" >&2
  exit 1
fi

echo "启动 Gazebo + Nav2 + AMCL（world=warehouse）"
echo "固定起点 S0: map(0.000, 0.000, yaw=0.000) <- config/localization.yaml"
echo "RViz: $RVIZ"
echo "日志: $LOG_FILE"
echo '按 Ctrl+C 可请求停止整套 launch。'
# Baseline start pose (measurement recorded in config/navigation_goals.yaml):
#   physical spawn = Gazebo world origin, facing +x   ->  x:=0 y:=0 z:=0 yaw:=0
#   AMCL initial   = the same pose in the map frame   ->  set_initial_pose in $LOCALIZATION_PARAMS
# The two happen to be identical because the map frame is axis-aligned with the Gazebo
# world frame (mean scan-vs-map residual 0.012 m at this pose, versus 3.14 m at the old
# hand-clicked value -0.094/-0.122/-3.122). Keep them equal: the dock is spawned at a
# yaw-dependent offset, so changing either one alone silently moves part of the scene.
# visualize_rays:=false disables Gazebo's per-ray visualisation of the lidar (640
# rays redrawn every frame under ogre2). It does not change physics, sensing or
# navigation, but it is pure rendering cost. Enable it only when debugging the
# lidar in Gazebo; keep it off for experiment runs.
ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py \
  world:=warehouse nav2:=true localization:=true slam:=false rviz:="$RVIZ" \
  visualize_rays:=false \
  x:=0.0 y:=0.0 z:=0.0 yaw:=0.0 \
  params:="$LOCALIZATION_PARAMS" \
  2>&1 | tee "$LOG_FILE"
