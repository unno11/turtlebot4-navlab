#!/usr/bin/env python3
"""NavLab: check the goal set against Nav2's own planner.

For every goal in GOALS this calls the Nav2 action /compute_path_to_pose
(planning only -- the robot does NOT move) and reports the planned path
length, how much the route actually turns, and the arrival heading, compared
against the locked baseline in config/navigation_goals.yaml.

What this is for now
--------------------
The goal set has been accepted: every route plans, lengths agree within 5%,
and the difficulty categories are backed by the numbers below. So this script
changed job -- it is a REGRESSION CHECK, not a selection tool. If a later run
disagrees with the baseline, something in the environment moved (map, planner
params, start pose, sensor mount). Treat that as a fault to investigate, not
as noise.

The offline 8-connected Dijkstra numbers that picked the candidates originally
are gone on purpose: they disagreed with Nav2 by -31%..+16%, so keeping them
around would only invite quoting the wrong ones.

Turn metric
-----------
Total absolute heading change along the route, sampled every 0.25 m. Counting
"steps whose heading changed by more than 30 deg" reports 0-1 on Nav2 paths,
because Smac emits smooth curves turning a few degrees per sample -- a real
90 deg bend scored as zero.

Goal yaw
--------
`yaw` must be the ARRIVAL heading of the route the planner actually takes.
If it is not, NavigateToPose adds an in-place rotation at the goal that no
metric records -- a hidden per-goal cost that makes cross-goal comparison
unfair.

Usage (Nav2 must already be running, robot parked at S0):
    source /opt/ros/jazzy/setup.bash
    /usr/bin/python3 scripts/check_paths.py
    /usr/bin/python3 scripts/check_paths.py G03      # single goal
"""

import math
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from builtin_interfaces.msg import Time
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose

# Locked baseline, mirrored from config/navigation_goals.yaml.
# id, category, x, y, yaw, base_len_m, base_turn_deg, map_bottleneck_m
GOALS = [
    ("G01", "simple",   5.735,   5.375,  0.734,  7.88,   3, 1.20),
    ("G02", "simple",  -6.145,   4.385,  2.557,  7.57,  10, 1.20),
    ("G03", "turning",  9.695,  16.265,  2.159, 24.78, 296, 1.00),
    ("G04", "turning", 12.665, -18.385, -1.000, 24.23, 155, 1.20),
    ("G05", "narrow",   7.715, -21.355, -1.726, 26.31, 201, 0.55),
    ("G06", "narrow",  -8.125,  -0.565,  2.713,  8.28, 117, 0.55),
    ("G07", "long",    -5.155,  23.195, -2.704, 42.57, 462, 1.00),
    ("G08", "long",    -2.185,  24.185,  2.924, 39.82, 369, 0.90),
]

RESAMPLE_STEP = 0.25      # metres between samples when measuring heading change
SHARP_THRESHOLD_DEG = 30.0
ARRIVAL_WINDOW = 0.5      # metres of path used to measure the arrival heading
ACTION_TIMEOUT = 30.0     # seconds per goal

# drift beyond these is a fault, not measurement noise
DRIFT_LEN_M = 0.5
DRIFT_TURN_DEG = 30.0
DRIFT_YAW_DEG = 5.0

# Goals that could not be planned at all. Drives the exit code so a caller (the batch
# runner) can gate on it instead of parsing stdout.
FAILURES = []


def yaw_to_quaternion(yaw):
    return 0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5)


def wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def path_points(msg):
    return [(p.pose.position.x, p.pose.position.y) for p in msg.poses]


def path_length(points):
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(points[i][0] - points[i - 1][0],
                            points[i][1] - points[i - 1][1])
    return total


def resample(points, step=RESAMPLE_STEP):
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    acc = 0.0
    for i in range(1, len(points)):
        acc += math.hypot(points[i][0] - points[i - 1][0],
                          points[i][1] - points[i - 1][1])
        if acc >= step:
            out.append(points[i])
            acc = 0.0
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def heading_stats(points):
    """Total absolute heading change (deg), net heading change (deg),
    and the number of single-sample jumps above SHARP_THRESHOLD_DEG."""
    pts = resample(points)
    headings = []
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        if math.hypot(dx, dy) < 1e-6:
            continue
        headings.append(math.atan2(dy, dx))
    if len(headings) < 2:
        return 0.0, 0.0, 0
    total = 0.0
    sharp = 0
    limit = math.radians(SHARP_THRESHOLD_DEG)
    for i in range(1, len(headings)):
        delta = wrap(headings[i] - headings[i - 1])
        total += abs(delta)
        if abs(delta) > limit:
            sharp += 1
    net = math.degrees(wrap(headings[-1] - headings[0]))
    return math.degrees(total), net, sharp


def arrival_yaw(points, window=ARRIVAL_WINDOW):
    """Heading of the last `window` metres of the raw path."""
    if len(points) < 2:
        return None
    acc = 0.0
    i = len(points) - 1
    while i > 0 and acc < window:
        acc += math.hypot(points[i][0] - points[i - 1][0],
                          points[i][1] - points[i - 1][1])
        i -= 1
    dx = points[-1][0] - points[i][0]
    dy = points[-1][1] - points[i][1]
    if math.hypot(dx, dy) < 1e-6:
        return None
    return math.atan2(dy, dx)


class PathVerifier(Node):
    def __init__(self):
        super().__init__('navlab_path_verifier')
        self.client = ActionClient(self, ComputePathToPose, 'compute_path_to_pose')

    def plan(self, x, y, yaw):
        if not self.client.wait_for_server(timeout_sec=15.0):
            raise RuntimeError(
                'action /compute_path_to_pose not available -- is Nav2 running?')

        goal = ComputePathToPose.Goal()

        # zero stamp means "use the latest available transform", avoiding any
        # sim-time / wall-time mismatch on the goal pose header
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = Time()
        pose.pose.position.x = float(x)
        pose.pose.position.y = float(y)
        qx, qy, qz, qw = yaw_to_quaternion(yaw)
        pose.pose.orientation.x = qx
        pose.pose.orientation.y = qy
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        goal.goal = pose

        start = PoseStamped()
        start.header.frame_id = 'map'
        start.header.stamp = Time()
        goal.start = start
        goal.planner_id = ''
        goal.use_start = False        # start from the live robot pose via TF

        send_future = self.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=ACTION_TIMEOUT)
        handle = send_future.result()
        if handle is None or not handle.accepted:
            return None, None, 'goal rejected'

        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=ACTION_TIMEOUT)
        wrapped = result_future.result()
        if wrapped is None:
            return None, None, 'no result (timeout)'

        res = wrapped.result
        if res.error_code != 0:
            return None, None, 'planner error_code=%d' % res.error_code
        if not res.path.poses:
            return None, None, 'empty path'
        return res.path, res.planning_time.sec + res.planning_time.nanosec * 1e-9, None

    def run(self, wanted):
        rows = []
        for gid, cat, x, y, yaw, blen, bturn, bottle in GOALS:
            if wanted and gid not in wanted:
                continue
            path, ptime, err = self.plan(x, y, yaw)
            if err:
                # Right after activation the planner can accept the action and still
                # reject the goal while its costmap settles. One retry after a short
                # pause keeps a transient from being reported as a goal-set fault.
                time.sleep(4.0)
                path, ptime, err = self.plan(x, y, yaw)
            if err:
                print('%s %-8s x=%+7.3f y=%+7.3f  FAILED: %s' % (gid, cat, x, y, err))
                FAILURES.append(gid)
                continue
            pts = path_points(path)
            length = path_length(pts)
            total_deg, net_deg, sharp = heading_stats(pts)
            sug = arrival_yaw(pts)
            dl = length - blen
            dt = total_deg - bturn
            dy = None if sug is None else math.degrees(wrap(sug - yaw))
            rate = total_deg / length if length > 0 else 0.0

            flags = []
            if abs(dl) > DRIFT_LEN_M:
                flags.append('LEN_DRIFT')
            if abs(dt) > DRIFT_TURN_DEG:
                flags.append('TURN_DRIFT')
            if dy is not None and abs(dy) > DRIFT_YAW_DEG:
                flags.append('YAW_DRIFT')

            rows.append(dict(gid=gid, cat=cat, x=x, y=y, yaw=yaw, length=length,
                             turn=total_deg, net=net_deg, sharp=sharp,
                             bottle=bottle, sug=sug, diff=dy, rate=rate,
                             blen=blen, bturn=bturn, flags=flags))
            print('%s %-8s len=%6.2f m (base %5.2f, %+5.2f)  '
                  'turn=%4.0f deg (base %3d, %+4.0f)  rate=%5.1f deg/m  '
                  'sug_yaw=%+6.3f (cmd %+6.3f, %+6.1f deg)  bottle=%.2f m  %s'
                  % (gid, cat, length, blen, dl, total_deg, bturn, dt, rate,
                     sug if sug is not None else float('nan'), yaw,
                     dy if dy is not None else float('nan'), bottle,
                     'OK' if not flags else ' '.join(flags)))
        return rows


def main():
    wanted = set(sys.argv[1:])
    rclpy.init()
    node = PathVerifier()
    try:
        rows = node.run(wanted)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    if not rows:
        print('ERROR: no goal could be planned')
        sys.exit(1)

    print('\n--- summary ---')
    for cat in ('simple', 'turning', 'narrow', 'long'):
        sub = [r for r in rows if r['cat'] == cat]
        if not sub:
            continue
        print('  %-8s len: %-16s m   turn: %-18s deg   rate: %-16s deg/m   bottleneck: %s m'
              % (cat,
                 ', '.join('%.1f' % r['length'] for r in sub),
                 ', '.join('%.0f' % r['turn'] for r in sub),
                 ', '.join('%.1f' % r['rate'] for r in sub),
                 ', '.join('%.2f' % r['bottle'] for r in sub)))

    bad = [r for r in rows if r['flags']]
    if bad:
        print('  DRIFT DETECTED: %s' % ', '.join(r['gid'] for r in bad))
        print('  -> map, planner params, start pose or sensor mount changed.')
        print('     Do not run trials until this is explained.')
    else:
        print('  no drift against baseline -- environment matches the locked goal set')

    if FAILURES:
        print('  UNPLANNABLE GOALS: %s' % ', '.join(FAILURES))
        sys.exit(1)
    if bad:
        sys.exit(1)


if __name__ == '__main__':
    main()
