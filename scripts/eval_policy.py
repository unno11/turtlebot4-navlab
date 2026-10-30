#!/usr/bin/env python3
"""Drive one goal with the learned policy and record the outcome.

The global planner is still Nav2's: this node asks planner_server for a path,
republishes it on /plan and lets scripts/policy_node.py produce /cmd_vel. That
keeps the planner fixed and makes the controller the only variable, the same
setup used for the MPPI/RPP/graceful comparison.

    python3 scripts/eval_policy.py --goal-id G02 --x -6.145 --y 4.385 --yaw 2.557
"""

import argparse
import json
import os
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose
from nav_msgs.msg import Path
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter
from tf2_ros import Buffer, TransformListener


class PolicyEval(Node):
    def __init__(self, args):
        super().__init__("policy_eval",
                         parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.args = args
        self.goal = (args.x, args.y)
        self.client = ActionClient(self, ComputePathToPose, "compute_path_to_pose")
        self.plan_pub = self.create_publisher(Path, "plan", 10)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.start_sim = None
        self.start_wall = time.monotonic()
        self.last_pos = None
        self.traveled = 0.0
        self.replans = 0
        self.plan_pending = False
        self.result = None
        self.next_replan = 0.0
        self.last_dist = None
        self.create_timer(0.5, self.on_tick)

    # ------------------------------------------------------------------ helpers
    def pose(self):
        try:
            tf = self.tf_buffer.lookup_transform("map", "base_link", rclpy.time.Time())
        except Exception:  # noqa: BLE001
            return None
        t = tf.transform.translation
        return float(t.x), float(t.y)

    def request_plan(self):
        if self.plan_pending or not self.client.server_is_ready():
            return
        goal = ComputePathToPose.Goal()
        ps = PoseStamped()
        ps.header.frame_id = "map"
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x = float(self.goal[0])
        ps.pose.position.y = float(self.goal[1])
        ps.pose.orientation.w = 1.0
        goal.goal = ps
        goal.use_start = False
        self.plan_pending = True
        self.client.send_goal_async(goal).add_done_callback(self.on_goal_response)

    def on_goal_response(self, future):
        handle = future.result()
        if not handle.accepted:
            self.plan_pending = False
            return
        handle.get_result_async().add_done_callback(self.on_plan)

    def on_plan(self, future):
        self.plan_pending = False
        result = future.result()
        if result is None or result.status != 4:  # 4 == STATUS_SUCCEEDED
            return
        self.plan_pub.publish(result.result.path)
        self.replans += 1

    # --------------------------------------------------------------------- loop
    def on_tick(self):
        now = self.get_clock().now()
        if self.start_sim is None:
            if now.nanoseconds == 0:  # /clock not received yet
                return
            self.start_sim = now
            self.request_plan()
            return

        elapsed = (now - self.start_sim).nanoseconds / 1e9
        p = self.pose()
        if p is not None:
            if self.last_pos is not None:
                self.traveled += float(np.hypot(p[0] - self.last_pos[0], p[1] - self.last_pos[1]))
            self.last_pos = p
            dist = float(np.hypot(p[0] - self.goal[0], p[1] - self.goal[1]))
            self.last_dist = dist
            if dist < 0.25:
                self.finish(True, elapsed, dist)
                return
        if elapsed > self.args.timeout:
            self.finish(False, elapsed, self.last_dist)
            return
        if elapsed >= self.next_replan:
            self.request_plan()
            self.next_replan = elapsed + self.args.replan_every

    def finish(self, ok, elapsed, dist):
        self.result = {
            "goal_id": self.args.goal_id,
            "success": bool(ok),
            "sim_time_s": round(elapsed, 2),
            "wall_time_s": round(time.monotonic() - self.start_wall, 2),
            "traveled_m": round(self.traveled, 2),
            "final_dist_m": None if dist is None else round(dist, 3),
            "replans": self.replans,
            "policy": os.path.basename(self.args.weights),
        }
        out = self.args.out
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(self.result, fh, indent=2, ensure_ascii=False)
        self.get_logger().info(f"{'SUCCESS' if ok else 'FAILED'} {self.result}")
        raise SystemExit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal-id", required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=600.0, help="simulation seconds")
    ap.add_argument("--replan-every", type=float, default=2.0)
    ap.add_argument("--weights", default="results/policy/bc_policy.npz")
    ap.add_argument("--out", default="results/policy_eval/run.json")
    args = ap.parse_args()
    rclpy.init()
    node = PolicyEval(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
