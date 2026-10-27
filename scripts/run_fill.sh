#!/usr/bin/env bash
# Top up the goal set to three valid runs per goal.
#
# The main batch consumes trial numbers even for runs that never produced data, so the
# two failure modes need different handling:
#   * launch never reached active -> no run record exists -> re-running the SAME trial
#     number works (run_batch only skips trials that have a finished record)
#   * record finished but failed   -> the trial number is burnt -> the goal needs an
#     additional trial number instead
#
# G01  t1 was lost to a host memory failure and a wall timeout; t2,t3 are valid -> t4
# G04  t2 lost the recorder; t1,t3 valid                                      -> t4
# G05  t2 never activated; t1,t3 valid                                        -> t2
# G06  t2 never activated; t1,t3 valid                                        -> t2
# G07  t3 never activated; t1,t2 valid                                        -> t3
set -uo pipefail
cd "$(dirname "$0")/.."

for spec in 4:G01 4:G04 3:G05 3:G06 3:G07; do
  echo "=== top-up: TRIALS=${spec%%:*} GOALS=${spec##*:} ==="
  TRIALS="${spec%%:*}" GOALS="${spec##*:}" ./scripts/run_batch.sh
done
