"""Real ROS Action protocol with a MOCK server; never runs Gazebo or records real trials."""
import argparse
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ['ROS_DOMAIN_ID'] = '187'
# multiprocessing has to spawn, not fork: the parent already carries DDS state from
# earlier imports and forking it leaves the child hung before it can signal ready.
# unittest discovery imports this module instead of running it as __main__, so this
# cannot live in the __main__ guard.
try:
    mp.set_start_method('spawn')
except RuntimeError:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
import navigation_run
import experiment_log as ledger


def server(mode, ready):
    import rclpy
    from rclpy.action import ActionServer, GoalResponse, CancelResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    rclpy.init()
    node = rclpy.create_node('mock_navlab_server')
    group = ReentrantCallbackGroup()
    od = node.create_publisher(Odometry, '/odom', 10)
    cl = node.create_publisher(Clock, '/clock', 10)
    count = [0]

    def publish():
        if mode == 'stalled':
            return
        count[0] += 1
        msg = Odometry()
        msg.header.frame_id = 'odom'
        msg.header.stamp.sec = count[0]
        msg.pose.pose.position.x = count[0] / 100
        od.publish(msg)
        c = Clock()
        c.clock.sec = count[0]
        cl.publish(c)

    def execute(handle):
        for i in range(100):
            if handle.is_cancel_requested:
                handle.canceled()
                return NavigateToPose.Result()
            f = NavigateToPose.Feedback()
            f.navigation_time.sec = i
            f.distance_remaining = 0.03
            f.number_of_recoveries = 1
            handle.publish_feedback(f)
            time.sleep(0.1)
            if mode in ('success', 'abort') and i >= 4:
                handle.succeed() if mode == 'success' else handle.abort()
                return NavigateToPose.Result()
        handle.abort()
        return NavigateToPose.Result()

    action = ActionServer(node, NavigateToPose, '/navigate_to_pose', execute,
        goal_callback=lambda req: GoalResponse.REJECT if mode == 'reject' else GoalResponse.ACCEPT,
        cancel_callback=lambda req: CancelResponse.ACCEPT, callback_group=group)
    timer = node.create_timer(0.05, publish, callback_group=group)
    ready.set()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except Exception:
        if rclpy.ok():
            raise


class ActionTests(unittest.TestCase):
    def run_case(self, mode, expected, reason, interrupt=False, shutdown=False):
        ready = mp.Event()
        proc = mp.Process(target=server, args=(mode, ready))
        proc.start()
        try:
            self.assertTrue(ready.wait(10))
            with tempfile.TemporaryDirectory() as tmp:
                ledger.RUNS = Path(tmp) / 'runs'
                ledger.SUMMARY = Path(tmp) / 'summary.csv'
                args = argparse.Namespace(goal_id='mock-only', trial=1, x=1., y=0., yaw=0.,
                    frame='map', action='/navigate_to_pose', odom='/odom', timeout=3.,
                    stale_timeout=0.8, cancel_grace=1., launch_log='', notes='MOCK SERVER TEST ONLY')
                timer = None
                if interrupt:
                    import threading
                    import signal
                    timer = threading.Timer(1.5, lambda: os.kill(os.getpid(), signal.SIGINT))
                    timer.start()
                if shutdown:
                    import threading
                    import rclpy
                    timer = threading.Timer(1.5, rclpy.shutdown)
                    timer.start()
                try:
                    navigation_run.execute(args, ledger)
                finally:
                    if timer:
                        timer.cancel()
                data = json.loads(next(ledger.RUNS.glob('*/run.json')).read_text())
                self.assertEqual(data['outcome'], expected)
                self.assertIn(reason, data['termination_reason'])
                self.assertIsNone(data['collisions'])
                self.assertIsNone(data['gazebo_rtf'])
                if mode == 'success':
                    self.assertEqual(data['action_status'], 4)
                    self.assertGreater(data['path_length_m'], 0)
                    self.assertEqual(data['recoveries'], 1)
                if mode in ('timeout', 'stalled') and not shutdown:
                    self.assertEqual(data['action_status'], 5)
                    self.assertEqual(data['cancellation'], 'confirmed')
        finally:
            proc.kill()
            proc.join(5)
            if proc.is_alive():
                proc.kill()

    def test_mock_success(self):
        self.run_case('success', 'succeeded', 'action_result')

    def test_mock_abort(self):
        self.run_case('abort', 'failed', 'action_result')

    def test_mock_reject(self):
        self.run_case('reject', 'failed', 'goal_rejected')

    def test_mock_timeout(self):
        self.run_case('timeout', 'failed', 'wall_timeout')

    def test_mock_simulation_stall(self):
        self.run_case('stalled', 'failed', 'simulation_stream_stalled')

    def test_mock_user_cancel(self):
        self.run_case('timeout', 'canceled', 'SIGINT', interrupt=True)

    def test_mock_ros_context_exit(self):
        self.run_case('timeout', 'failed', 'ros_or_client_error', shutdown=True)


if __name__ == '__main__':
    unittest.main()
