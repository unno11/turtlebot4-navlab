#!/usr/bin/env bash
# Top the three controller arms back up to eight records each.
#
# Four trials were lost to the Gazebo startup race (controller_manager never came up,
# so spawners died and Nav2 never activated). Those attempts never reached the
# navigation step and produced no record at all - they are not navigation results, so
# they are re-run rather than reported as failures. The G05 failures in the rpp and
# graceful arms are real navigation results and are deliberately NOT re-run.

set -uo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

fill() {
  local arm="$1" goals="$2"
  echo "[$(date +%H:%M:%S)] filling arm $arm: $goals"
  CONTROL="$arm" TRIALS=1 GOALS="$goals" ./scripts/run_batch.sh
  echo "[$(date +%H:%M:%S)] arm $arm fill batch exit $?"

  mkdir -p "results/archive/ctl_$arm/runs"
  if compgen -G "results/runs/*" > /dev/null; then
    mv results/runs/* "results/archive/ctl_$arm/runs/"
  fi
  rm -f results/summary.csv
  rmdir results/runs 2>/dev/null || true
  echo "[$(date +%H:%M:%S)] arm $arm now has $(ls "results/archive/ctl_$arm/runs" | wc -l) record(s)"
}

fill mppi "G01"
fill rpp "G07 G08"
fill graceful "G08"

echo "[$(date +%H:%M:%S)] fill finished"
