#!/usr/bin/env python3
"""Decide what a run record is worth, in one place.

Both the summariser and the batch runner need the same answer to "did this trial
produce a navigation result?", and they used to answer it differently: the
summariser looked at termination_reason and action_status, the batch runner only
looked at state == "finished". That let a record which produced no navigation
result block a re-run, and it meant the two tools could disagree about the same
file.

Verdicts:

  succeeded   the action returned SUCCEEDED (status 4)
  failed      the action returned ABORTED (status 6)
  invalid     the record exists but holds no navigation result: the harness gave up
              (wall timeout, stalled stream, ROS context loss) before the action
              returned. This says nothing about navigation capability, so it must
              neither count as a failure nor block a retry.
  unfinished  the recorder never finalised the record

Note on RTF: docs/experiment_logging.md recommends measuring the real-time factor
before a batch and not running below 0.5. The recorded batches did not meet that
gate - they ran at roughly 0.19-0.30 - so the gate is reported as context rather
than applied as a classifier here. Filtering on it now would discard every record
including the ones that succeeded, which is not a correction, it is a different
experiment. See the note in that document for what this costs and what it does not.
"""

SAFE_VERDICTS = ("succeeded", "failed")


def control_of(record):
    """Which controller arm a record belongs to, or '' when it predates the switch."""
    notes = record.get("notes_start") or ""
    for part in notes.split(";"):
        part = part.strip()
        if part.startswith("control="):
            return part.split("=", 1)[1].strip()
    return ""


def verdict(record):
    """Return (verdict, reason)."""
    if record.get("state") != "finished":
        return "unfinished", "state=%s" % record.get("state")

    reason = record.get("termination_reason")
    status = record.get("action_status")

    if reason != "action_result":
        return "invalid", str(reason or "no_action_result")
    if status == 4:
        return "succeeded", ""
    if status == 6:
        return "failed", ""
    return "invalid", "action_status=%s" % status


def is_result(record):
    """True when the record contributes to the success rate."""
    return verdict(record)[0] in SAFE_VERDICTS


def blocks_rerun(record, arm=""):
    """True when this record means the trial does not need to be run again.

    Only a real result from the same arm counts. An invalid record must be retried,
    and a record from another arm is not the same trial: the controller is part of
    the experiment's identity, not an implementation detail.
    """
    if verdict(record)[0] not in SAFE_VERDICTS:
        return False
    if arm and control_of(record) != arm:
        return False
    return True


def _main(argv):
    import json
    import sys

    if len(argv) < 3:
        print(__doc__)
        return 2
    action, path = argv[1], argv[2]
    record = json.loads(open(path, encoding="utf-8").read())

    if action == "verdict":
        word, reason = verdict(record)
        print("%s %s" % (word, reason))
        return 0
    if action == "blocks-rerun":
        arm = argv[3] if len(argv) > 3 else ""
        return 0 if blocks_rerun(record, arm) else 1

    print("unknown action: %s" % action)
    return 2


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv))
