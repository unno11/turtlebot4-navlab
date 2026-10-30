#!/usr/bin/env python3
"""Run a behaviour-cloning policy as the local controller.

Subscribes to the global plan and laser, publishes /cmd_vel. Inference is plain
numpy, so this node does not need torch installed.

    python3 scripts/policy_node.py --weights results/policy/bc_policy.npz
"""

import argparse
import os
import sys

import numpy as np
import rclpy
from geometry_msgs.msg import TwistStamped
from nav_msgs.msg import Path
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bc_common import Policy, build_obs  # noqa: E402


class PolicyController(Node):
    def __init__(self, weights, rate, max_speed, dump_obs=None):
        super().__init__("bc_policy_controller",
                         parameter_overrides=[Parameter("use_sim_time", Parameter.Type.BOOL, True)])
        self.policy = Policy(weights)
        self.max_speed = max_speed
        self.dump_path = dump_obs
        self.dumped = []
        self.ranges = None
        self.path_xy = None
        self.last_plan_time = None
        self.w_prev = 0.0
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        # Publish upstream of the velocity smoother and collision monitor, so the
        # policy's commands pass through the same safety chain Nav2 uses:
        # cmd_vel_nav -> velocity_smoother -> cmd_vel_smoothed -> collision_monitor -> cmd_vel
        self.pub = self.create_publisher(TwistStamped, "cmd_vel_nav", 10)
        self.create_subscription(LaserScan, "scan", self.on_scan, 10)
        self.create_subscription(Path, "plan", self.on_plan, 10)
        self.create_timer(1.0 / rate, self.on_tick)

    def on_scan(self, msg):
        self.ranges = np.asarray(msg.ranges, dtype=np.float32)

    def on_plan(self, msg):
        if len(msg.poses) >= 2:
            self.path_xy = np.array([[p.pose.position.x, p.pose.position.y] for p in msg.poses])
            self.last_plan_time = self.get_clock().now()

    def _msg(self, v=0.0, w=0.0):
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.twist.linear.x = v
        msg.twist.angular.z = w
        return msg

    def stop(self):
        self.pub.publish(self._msg())

    def on_tick(self):
        if self.ranges is None or self.path_xy is None or self.last_plan_time is None:
            self.stop()
            return
        age = (self.get_clock().now() - self.last_plan_time).nanoseconds / 1e9
        if age > 3.0:  # plan went stale: stop rather than drive blind
            self.stop()
            return
        try:
            tf = self.tf_buffer.lookup_transform("map", "base_link", rclpy.time.Time())
        except Exception:  # noqa: BLE001
            self.stop()
            return
        t = tf.transform.translation
        q = tf.transform.rotation
        yaw = np.arctan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        obs = build_obs(self.ranges, self.path_xy, (t.x, t.y), yaw, self.path_xy[-1], self.w_prev)
        v, w = self.policy(obs)
        v = max(-self.max_speed, min(self.max_speed, v))
        if self.dump_path and len(self.dumped) < 300:
            self.dumped.append(np.concatenate([[v, w], obs]))
            np.savez_compressed(self.dump_path, data=np.stack(self.dumped))
        self.w_prev = w
        self.pub.publish(self._msg(v, w))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="results/policy/bc_policy.npz")
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--max-speed", type=float, default=0.5)
    ap.add_argument("--dump-obs", default=None, help="write the first 300 observations here for comparison with training data")
    args = ap.parse_args()
    rclpy.init()
    node = PolicyController(args.weights, args.rate, args.max_speed, args.dump_obs)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if rclpy.ok():
            node.stop()  # never publish through a dead context
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
