#!/usr/bin/env bash
# Evaluate one trained policy on one goal: fresh simulation, policy as the local
# controller, Nav2's planner kept in the loop.
#
#   ./scripts/eval_policy.sh results/policy/bc_all.npz G02 results/policy_eval/all_G02.json
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

WEIGHTS="${1:?usage: eval_policy.sh <weights.npz> <goal-id> <out.json> [timeout_sim_s]}"
GOAL_ID="${2:?goal id, e.g. G02}"
OUT="${3:?output json path}"
TIMEOUT="${4:-600}"

LOG_DIR="$HOME/turtlebot4_ws/log/navlab"
mkdir -p "$LOG_DIR" "$(dirname "$OUT")"

set +u
source /opt/ros/jazzy/setup.bash
set -u

log() { echo "[$(date +%H:%M:%S)] $*"; }

read -r X Y YAW <<< "$(/usr/bin/python3 - "$GOAL_ID" <<'PY'
import sys, yaml
gid = sys.argv[1]
d = yaml.safe_load(open("config/navigation_goals.yaml", encoding="utf-8"))
g = d["goals"][gid]
print(f'{g["x"]} {g["y"]} {g["yaw"]}')
PY
)"

wait_nav() {
  local deadline=$((SECONDS + 300)) active
  while (( SECONDS < deadline )); do
    active=0
    for n in amcl bt_navigator planner_server; do
      ros2 lifecycle get "/$n" 2>/dev/null | grep -q "active" && active=$((active + 1))
    done
    (( active == 3 )) && return 0
    sleep 5
  done
  return 1
}

stop_all() {
  pkill -INT -f "policy_node.py" 2>/dev/null
  pkill -INT -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    pgrep -f "gz sim" >/dev/null 2>&1 || { sleep 2; return 0; }
    sleep 2
  done
  pkill -TERM -f "gz sim" 2>/dev/null; sleep 5
  pkill -KILL -f "gz sim" 2>/dev/null; sleep 2
}
trap 'stop_all' EXIT

log "goal $GOAL_ID  weights $(basename "$WEIGHTS")"
CONTROL=mppi RVIZ=false ./scripts/start_navigation.sh >"$LOG_DIR/policy_${GOAL_ID}_$(date +%Y%m%d_%H%M%S).log" 2>&1 &
wait_nav || { log "ERROR: Nav2 did not become active"; exit 1; }
log "Nav2 active"

/usr/bin/python3 scripts/policy_node.py --weights "$WEIGHTS" >"$LOG_DIR/policy_node_${GOAL_ID}.log" 2>&1 &
sleep 3

/usr/bin/python3 scripts/eval_policy.py \
  --goal-id "$GOAL_ID" --x "$X" --y "$Y" --yaw "$YAW" \
  --weights "$WEIGHTS" --out "$OUT" --timeout "$TIMEOUT"
RC=$?
log "eval finished (rc=$RC) -> $OUT"
exit $RC
