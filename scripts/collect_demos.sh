#!/usr/bin/env bash
# Collect behaviour-cloning demonstrations: for each goal, start a fresh
# simulation, let Nav2 (MPPI) drive it while scripts/collect_expert.py records,
# then tear everything down. One file per goal under results/demos/.
#
#   GOALS="G02 G06" ./scripts/collect_demos.sh
#
# The simulator is started without RViz so the real-time factor stays as high as
# this machine allows; nothing here needs a display.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

GOALS="${GOALS:-G02 G06 G03}"
OUTDIR="${OUTDIR:-results/demos}"
LOG_DIR="$HOME/turtlebot4_ws/log/navlab"
mkdir -p "$OUTDIR" "$LOG_DIR"

set +u
source /opt/ros/jazzy/setup.bash
set -u

log() { echo "[$(date +%H:%M:%S)] $*"; }

goal_fields() {
  /usr/bin/python3 - "$1" <<'PY'
import math, sys, yaml
gid = sys.argv[1]
d = yaml.safe_load(open("config/navigation_goals.yaml", encoding="utf-8"))
g = d["goals"][gid]
half = g["yaw"] / 2.0
print(f'{g["x"]} {g["y"]} {math.sin(half)} {math.cos(half)}')
PY
}

wait_nav() {
  local deadline=$((SECONDS + 300)) active
  while (( SECONDS < deadline )); do
    active=0
    for n in amcl bt_navigator controller_server planner_server collision_monitor velocity_smoother; do
      ros2 lifecycle get "/$n" 2>/dev/null | grep -q "active" && active=$((active + 1))
    done
    (( active == 6 )) && return 0
    sleep 5
  done
  return 1
}

stop_sim() {
  pkill -INT -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    pgrep -f "gz sim" >/dev/null 2>&1 || pgrep -f "ros2 launch turtlebot4_gz_bringup" >/dev/null 2>&1 || { sleep 2; return 0; }
    sleep 2
  done
  pkill -TERM -f "gz sim" 2>/dev/null
  pkill -TERM -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  sleep 5
  pkill -KILL -f "gz sim" 2>/dev/null
  pkill -KILL -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  sleep 2
}

for g in $GOALS; do
  read -r X Y QZ QW <<< "$(goal_fields "$g")"
  log "=== $g  x=$X y=$Y ==="

  ATTEMPT=0; READY=0
  while (( ATTEMPT < 2 && READY == 0 )); do
    ATTEMPT=$((ATTEMPT + 1))
    LAUNCH_LOG="$LOG_DIR/collect_${g}_$(date +%Y%m%d_%H%M%S).log"
    CONTROL=mppi RVIZ=false ./scripts/start_navigation.sh >"$LAUNCH_LOG" 2>&1 &
    LAUNCH_PID=$!
    log "launch started (attempt $ATTEMPT, pid $LAUNCH_PID, log $LAUNCH_LOG)"

    if wait_nav; then
      READY=1
      log "Nav2 active"
    else
      log "ERROR: Nav2 did not become active within 300s, tearing down and retrying"
      stop_sim
    fi
  done
  if (( READY == 0 )); then
    log "ERROR: giving up on $g"
    continue
  fi

  OUT="$OUTDIR/${g}_$(date +%Y%m%dT%H%M%S)"
  /usr/bin/python3 scripts/collect_expert.py --out "$OUT" --duration 1800 >"$OUTDIR/.collect_$g.log" 2>&1 &
  COLL_PID=$!
  sleep 3

  log "sending goal"
  SENT=0
  for try in 1 2 3; do
    timeout 1200 ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
      "{pose: {header: {frame_id: map}, pose: {position: {x: $X, y: $Y, z: 0.0}, orientation: {z: $QZ, w: $QW}}}}" \
      >"$OUTDIR/.goal_$g.log" 2>&1
    if grep -q "SUCCEEDED" "$OUTDIR/.goal_$g.log"; then
      log "goal succeeded"
      SENT=1
      break
    fi
    if grep -qi "rejected" "$OUTDIR/.goal_$g.log"; then
      # bt_navigator accepts the goal but the costmaps are not ready yet right
      # after activation; a short wait and a second attempt clears it.
      log "goal rejected, waiting 8s and retrying ($try/3)"
      sleep 8
      continue
    fi
    log "goal did not succeed (see $OUTDIR/.goal_$g.log)"
    break
  done
  (( SENT == 0 )) && log "no successful goal for $g"

  kill -INT "$COLL_PID" 2>/dev/null
  wait "$COLL_PID" 2>/dev/null
  log "collector stopped"

  stop_sim
  log "simulation stopped"
done

log "done; demonstrations in $OUTDIR"
ls -1 "$OUTDIR"/*.npz 2>/dev/null | while read -r f; do echo "  $f"; done
