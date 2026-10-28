#!/usr/bin/env bash
# Run the controller comparison matrix: every goal once per controller.
#
# Each arm is run to completion and then moved into results/archive/ctl_<arm>/ before
# the next arm starts. The batch runner skips trials it considers finished, and it
# cannot tell two arms apart on its own, so without this archiving step the second
# and third arms would silently do nothing.
#
# Usage:
#   ./scripts/run_controller_matrix.sh                 # 1 trial per goal per arm
#   TRIALS=3 ./scripts/run_controller_matrix.sh        # 3 trials per goal per arm
#   ARMS="rpp graceful" ./scripts/run_controller_matrix.sh

set -uo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

TRIALS="${TRIALS:-1}"
ARMS="${ARMS:-mppi rpp graceful}"

stamp() { date +%H:%M:%S; }

for arm in $ARMS; do
  echo "[$(stamp)] ===== arm: $arm ($TRIALS trial(s) per goal) ====="
  CONTROL="$arm" TRIALS="$TRIALS" ./scripts/run_batch.sh
  rc=$?
  echo "[$(stamp)] arm $arm finished (batch exit $rc)"

  mkdir -p "results/archive/ctl_$arm"
  if [[ -d results/runs ]]; then
    mv results/runs "results/archive/ctl_$arm/runs"
  fi
  if [[ -f results/summary.csv ]]; then
    mv results/summary.csv "results/archive/ctl_$arm/summary.csv"
  fi
  echo "[$(stamp)] arm $arm archived to results/archive/ctl_$arm"
done

echo "[$(stamp)] controller matrix finished"
echo "summarise an arm with: /usr/bin/python3 scripts/summarize_results.py --runs results/archive/ctl_<arm>/runs"
