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
echo "启动 Gazebo + Nav2 + AMCL + RViz（world=warehouse）"
echo "日志: $LOG_FILE"
echo '按 Ctrl+C 可请求停止整套 launch。'
ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py \
  world:=warehouse nav2:=true localization:=true slam:=false rviz:=true \
  2>&1 | tee "$LOG_FILE"
