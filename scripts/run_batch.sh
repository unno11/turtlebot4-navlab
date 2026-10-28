#!/usr/bin/env bash
# Batch experiment runner for the NavLab goal set.
#
# For every goal in config/navigation_goals.yaml and every trial number it:
#   1. starts the full simulation fresh,
#   2. waits until the six Nav2/AMCL nodes report active,
#   3. runs scripts/check_paths.py as an environment gate,
#   4. sends the goal with scripts/experiment_log.py navigate,
#   5. stops the simulation and waits until it is really gone.
#
# The full restart between trials is deliberate, not wasteful: reproducible start pose
# requires a fresh Gazebo spawn AND a fresh AMCL seed. Chaining goals inside one launch
# would silently change the start pose of every trial after the first.
#
# Usage:
#   PLAN=1 ./scripts/run_batch.sh                    # print the schedule, run nothing
#   TRIALS=3 ./scripts/run_batch.sh                  # run the whole set
#   TRIALS=3 GOALS="G01 G02" ./scripts/run_batch.sh  # subset, useful for a smoke test
#   SKIP_DONE=0 TRIALS=3 ./scripts/run_batch.sh      # redo trials that already finished
#
# Environment:
#   TRIALS          trials per goal                     (default 3)
#   GOALS           space separated goal ids to run     (default: all in the yaml)
#   SKIP_DONE       1 = skip trials with a finished run (default 1, makes restarts cheap)
#   READY_TIMEOUT   seconds to wait for Nav2 to become active   (default 300)
#   STOP_TIMEOUT    seconds to wait for a clean shutdown        (default 60)
#   TRIAL_TIMEOUT   wall-clock budget per navigation            (default 1800)
#   STALE_TIMEOUT   sim clock / odom stall budget               (default 30)
#   PLAN            1 = dry run, only print the schedule        (default 0)
#   CONTROL         mppi | rpp | graceful, which local controller to run (default mppi)
#                   The three parameter files differ only in the FollowPath block, so
#                   the only variable between arms is the control law. The arm is
#                   recorded in notes_start of every run.
#
# Exit code: 0 if every attempted trial ended with outcome=succeeded, 1 otherwise.

set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TRIALS="${TRIALS:-3}"
GOALS="${GOALS:-}"
SKIP_DONE="${SKIP_DONE:-1}"
READY_TIMEOUT="${READY_TIMEOUT:-300}"
STOP_TIMEOUT="${STOP_TIMEOUT:-60}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-1800}"
STALE_TIMEOUT="${STALE_TIMEOUT:-30}"
PLAN="${PLAN:-0}"
CONTROL="${CONTROL:-mppi}"

BATCH_LOG="results/batch_$(date +%Y%m%d_%H%M%S).log"
NODES="amcl bt_navigator controller_server planner_server collision_monitor velocity_smoother"

log() {
  local line
  line="[$(date +%H:%M:%S)] $*"
  printf '%s\n' "$line"
  [[ "$PLAN" == "1" ]] || printf '%s\n' "$line" >>"$BATCH_LOG"
}

die() { log "FATAL: $*"; exit 1; }

# ---------------------------------------------------------------- goal table

goal_rows() {
  /usr/bin/python3 - <<'PY'
import sys, yaml
cfg = yaml.safe_load(open('config/navigation_goals.yaml', encoding='utf-8'))
for gid, g in cfg['goals'].items():
    print(gid, g['category'], g['x'], g['y'], g['yaw'])
PY
}

wanted_goal() {
  [[ -z "$GOALS" ]] && return 0
  local g
  for g in $GOALS; do [[ "$g" == "$1" ]] && return 0; done
  return 1
}

# ---------------------------------------------------------------- state checks

sim_running() { pgrep -f "gz sim" >/dev/null 2>&1; }

already_done() {
  local gid="$1" t="$2" f
  [[ "$SKIP_DONE" == "1" ]] || return 1
  for f in results/runs/*_"${gid}"_t$(printf '%02d' "$t")_*/run.json; do
    [[ -e "$f" ]] || continue
    if /usr/bin/python3 -c \
        'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("state")=="finished" else 1)' \
        "$f" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

wait_active() {
  local deadline=$((SECONDS + READY_TIMEOUT)) n state all
  while (( SECONDS < deadline )); do
    all=1
    for n in $NODES; do
      state=$(timeout 5 ros2 lifecycle get "/$n" 2>/dev/null | head -1)
      [[ "$state" == active* ]] || { all=0; break; }
    done
    (( all == 1 )) && return 0
    sleep 3
  done
  return 1
}

stop_sim() {
  local pid="${1:-}" deadline
  if [[ -n "$pid" ]]; then
    kill -INT "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null
  fi
  pkill -INT -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  deadline=$((SECONDS + STOP_TIMEOUT))
  while (( SECONDS < deadline )); do
    sim_running || { sleep 2; return 0; }
    sleep 2
  done
  log "  WARN: simulation still alive after ${STOP_TIMEOUT}s, escalating to TERM"
  pkill -TERM -f "gz sim" 2>/dev/null
  pkill -TERM -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
  sleep 8
  if sim_running; then
    log "  WARN: escalating to KILL"
    pkill -KILL -f "gz sim" 2>/dev/null
    pkill -KILL -f "ros2 launch turtlebot4_gz_bringup" 2>/dev/null
    sleep 5
  fi
  sim_running && { log "  ERROR: could not stop the simulation"; return 1; }
  return 0
}

# ---------------------------------------------------------------- main

if [[ "$PLAN" != "1" ]]; then
  # ROS 2 setup scripts are not nounset-safe, so relax -u only while sourcing them.
  set +u
  source /opt/ros/jazzy/setup.bash
  set -u
  sim_running && die "a simulation is already running -- stop it before starting the batch"
  [[ -f config/navigation_goals.yaml ]] || die "config/navigation_goals.yaml not found"
  [[ -x scripts/check_paths.py ]] || chmod +x scripts/check_paths.py 2>/dev/null
  mkdir -p results
  log "batch log: $BATCH_LOG"
  log "local controller arm: $CONTROL"
fi

schedule=()
while read -r gid cat x y yaw; do
  wanted_goal "$gid" || continue
  for t in $(seq 1 "$TRIALS"); do
    schedule+=("$gid|$cat|$x|$y|$yaw|$t")
  done
done < <(goal_rows)

(( ${#schedule[@]} > 0 )) || die "no goals selected"

if [[ "$PLAN" == "1" ]]; then
  printf 'PLAN: %d goal(s) x %d trial(s) = %d run(s)\n' \
    "$(printf '%s\n' "${schedule[@]}" | cut -d'|' -f1 | sort -u | wc -l)" \
    "$TRIALS" "${#schedule[@]}"
  printf '%-6s %-8s %8s %8s %8s %6s %s\n' GOAL CATEGORY X Y YAW TRIAL ACTION
  for row in "${schedule[@]}"; do
    IFS='|' read -r gid cat x y yaw t <<<"$row"
    if already_done "$gid" "$t"; then act="skip (finished)"; else act="run"; fi
    printf '%-6s %-8s %8.3f %8.3f %8.3f %6s %s\n' "$gid" "$cat" "$x" "$y" "$yaw" "$t" "$act"
  done
  exit 0
fi

total=${#schedule[@]}
index=0
failed=0
skipped=0
launch_pid=""

cleanup() {
  [[ -n "$launch_pid" ]] && stop_sim "$launch_pid"
  return 0
}
on_signal() {
  log "interrupted -- stopping the simulation and exiting"
  cleanup
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

for row in "${schedule[@]}"; do
  IFS='|' read -r gid cat x y yaw t <<<"$row"
  index=$((index + 1))

  if already_done "$gid" "$t"; then
    log "[$index/$total] $gid trial $t -- already finished, skipping"
    skipped=$((skipped + 1))
    continue
  fi

  log "[$index/$total] $gid trial $t ($cat) x=$x y=$y yaw=$yaw"

  stop_sim "" >/dev/null 2>&1
  sim_running && die "simulation still running before $gid t$t -- refusing to start a second one"

  # Batch runs are headless: RViz is a pure subscriber and only costs CPU here.
  setsid env RVIZ="${RVIZ:-false}" CONTROL="$CONTROL" bash ./scripts/start_navigation.sh >/dev/null 2>&1 &
  launch_pid=$!
  log "  launch started (pgid $launch_pid)"

  if ! wait_active; then
    log "  ERROR: Nav2 did not become active within ${READY_TIMEOUT}s"
    failed=$((failed + 1))
    stop_sim "$launch_pid" || true
    launch_pid=""
    continue
  fi
  log "  Nav2 active"

  if ! /usr/bin/python3 scripts/check_paths.py "$gid" >>"$BATCH_LOG" 2>&1; then
    log "  ERROR: check_paths reported drift or a planning failure"
    failed=$((failed + 1))
    stop_sim "$launch_pid" || true
    launch_pid=""
    continue
  fi
  log "  self-check passed"

  /usr/bin/python3 scripts/experiment_log.py navigate \
    --goal-id "$gid" --trial "$t" \
    --x "$x" --y "$y" --yaw "$yaw" \
    --notes "control=$CONTROL" \
    --timeout "$TRIAL_TIMEOUT" --stale-timeout "$STALE_TIMEOUT" \
    >/dev/null 2>&1
  rc=$?

  outcome=$(/usr/bin/python3 - "$gid" "$t" <<'PY'
import glob, json, sys
gid, t = sys.argv[1], int(sys.argv[2])
hits = sorted(glob.glob('results/runs/*_%s_t%02d_*/run.json' % (gid, t)))
for f in reversed(hits):
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    if d.get('state') == 'finished':
        print('%s rtf_estimate=%.3f' % (
            d.get('outcome'),
            (d.get('nav_time_sim_s') or 0) / (d.get('duration_wall_s') or 1)))
        break
else:
    print('NO_RECORD')
PY
)
  log "  result: $outcome (exit $rc)"
  [[ "$rc" == "0" ]] || failed=$((failed + 1))

  stop_sim "$launch_pid" || log "  WARN: shutdown was not clean"
  launch_pid=""
  sleep 5
done

log "batch finished: $((total - skipped - failed)) ok, $failed not ok, $skipped skipped"
log "records in results/runs/, summary in results/summary.csv"
[[ "$failed" == "0" ]] && exit 0 || exit 1
