#!/usr/bin/env python3
"""Record expert demonstrations while Nav2 drives a goal.

Writes (observation, action) pairs where the action is the command Nav2's
controller actually issued. Run it next to a normal navigation run; it does not
publish anything itself.

    python3 scripts/collect_expert.py --out results/demos/G02_1 --duration 180
"""

import argparse
import os
import sys
import time

import numpy as np
import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Path
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bc_common import ACT_DIM, OBS_DIM, build_obs  # noqa: E402


class Collector(Node):
    def __init__(self, out_path, duration, rate):
        super().__init__("expert_collector")
        self.out_path = out_path
        self.deadline = time.monotonic() + duration
        self.obs, self.act = [], []
        self.ranges = None
        self.path_xy = None
        self.w_prev = 0.0
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(LaserScan, "scan", self.on_scan, 10)
        self.create_subscription(Path, "plan", self.on_plan, 10)
        # /cmd_vel is TwistStamped in this stack (Jazzy + collision_monitor).
        # It is the command that actually reaches the base, which is the label
        # we want: the motion the expert's action produced.
        self.create_subscription(TwistStamped, "cmd_vel", self.on_cmd, 10)
        self.create_timer(1.0 / rate, self.on_tick)
        self.skipped = 0

    def on_scan(self, msg):
        self.ranges = np.asarray(msg.ranges, dtype=np.float32)

    def on_plan(self, msg):
        if len(msg.poses) >= 2:
            self.path_xy = np.array([[p.pose.position.x, p.pose.position.y] for p in msg.poses])

    def on_cmd(self, msg):
        self.last_v = float(msg.twist.linear.x)
        self.w_prev = float(msg.twist.angular.z)

    def on_tick(self):
        if time.monotonic() > self.deadline:
            self.finish()
            return
        if self.ranges is None or self.path_xy is None:
            self.skipped += 1
            return
        try:
            tf = self.tf_buffer.lookup_transform("map", "base_link", rclpy.time.Time())
        except Exception:  # noqa: BLE001 - transform may not exist yet
            self.skipped += 1
            return
        t = tf.transform.translation
        q = tf.transform.rotation
        yaw = np.arctan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        goal = self.path_xy[-1]
        obs = build_obs(self.ranges, self.path_xy, (t.x, t.y), yaw, goal)
        self.obs.append(obs)
        self.act.append(np.array([self.last_v, self.w_prev], dtype=np.float32))

    last_v = 0.0

    def save(self):
        if len(self.obs) < 20:
            self.get_logger().warn(f"only {len(self.obs)} samples collected, nothing written")
            return False
        obs = np.stack(self.obs)
        act = np.stack(self.act)
        os.makedirs(os.path.dirname(self.out_path) or ".", exist_ok=True)
        np.savez_compressed(self.out_path + ".npz", obs=obs, act=act,
                            obs_dim=OBS_DIM, act_dim=ACT_DIM)
        self.get_logger().info(f"wrote {self.out_path}.npz  samples={len(obs)}  skipped={self.skipped}")
        return True

    def finish(self):
        raise SystemExit(0 if self.save() else 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output prefix, .npz appended")
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--rate", type=float, default=10.0)
    args = ap.parse_args()

    rclpy.init()
    node = Collector(args.out, args.duration, args.rate)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.save()  # also on Ctrl+C / SIGTERM: never lose a demonstration
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
