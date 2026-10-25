"""Single-goal ROS adapter. No ROS imports for ledger-only commands or unit tests."""
import math
import signal
import time
import uuid


def outcome_for_status(status):
    return {4: 'succeeded', 5: 'canceled'}.get(status, 'failed')


class Metrics:
    def __init__(self):
        self.previous = None
        self.samples = 0
        self.length = 0.0
        self.invalid = None
        self.feedback = {}

    def odom(self, x, y, frame, stamp):
        if not all(math.isfinite(v) for v in (x, y)):
            self.invalid = 'nonfinite odometry'
            return
        if self.previous:
            px, py, pf, pt = self.previous
            if frame != pf or stamp < pt:
                self.invalid = 'odometry frame changed or timestamp moved backwards'
            elif stamp == pt:
                return
            else:
                self.length += math.hypot(x - px, y - py)
        self.previous = (x, y, frame, stamp)
        self.samples += 1

    def values(self):
        return dict(self.feedback, path_length_m=(self.length if self.samples >= 2 and not self.invalid else None),
                    path_length_source='odom estimate, not Gazebo ground truth',
                    odom_samples=self.samples, odom_error=self.invalid)


def add_arguments(p):
    p.add_argument('--goal-id', required=True)
    p.add_argument('--trial', type=int, default=1)
    for name in ('x', 'y', 'yaw'):
        p.add_argument('--' + name, type=float, required=True)
    p.add_argument('--frame', default='map')
    p.add_argument('--action', default='/navigate_to_pose')
    p.add_argument('--odom', default='/odom')
    p.add_argument('--timeout', type=float, default=300, help='整个任务墙钟上限，秒')
    p.add_argument('--stale-timeout', type=float, default=30, help='仿真时钟不前进或里程计中断上限，墙钟秒')
    p.add_argument('--cancel-grace', type=float, default=5)
    p.add_argument('--launch-log', default='')
    p.add_argument('--notes', default='')


def execute(args, ledger):
    for key in ('x', 'y', 'yaw', 'timeout', 'stale_timeout', 'cancel_grace'):
        value = getattr(args, key)
        if not math.isfinite(value) or (key in ('timeout', 'stale_timeout', 'cancel_grace') and value <= 0):
            raise ValueError(f'Invalid {key}')
    # Fail before creating a run if the ROS installation has not been sourced.
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.signals import SignalHandlerOptions
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.parameter import Parameter
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from unique_identifier_msgs.msg import UUID

    record = ledger.start(args)
    rid = record['run_id']
    started = time.monotonic()
    metrics = Metrics()
    node = client = handle = send_future = result_future = None
    active = False
    last_odom = last_clock = started
    clock_value = None
    action_status = None
    outcome = 'failed'
    reason = 'exception'
    error = ''
    cancel_state = 'not_requested'
    interrupted = []
    old_signals = {}
    last_checkpoint = started
    action_uuid = uuid.uuid4().bytes
    ledger.checkpoint(rid, dict(source='ros2_action', action_name=args.action,
        action_goal_uuid=action_uuid.hex(), goal_pose=dict(x=args.x, y=args.y, yaw=args.yaw, frame=args.frame),
        metrics_source='last received NavigateToPose feedback', use_sim_time=True))

    def save():
        ledger.checkpoint(rid, dict(metrics.values(), action_status=action_status,
                                   heartbeat_utc=ledger.timestamp(ledger.now_utc())))

    def odom(msg):
        nonlocal last_odom
        if active:
            last_odom = time.monotonic()
            pos = msg.pose.pose.position
            stamp = msg.header.stamp.sec * 1000000000 + msg.header.stamp.nanosec
            metrics.odom(pos.x, pos.y, msg.header.frame_id, stamp)

    def clock(msg):
        nonlocal clock_value, last_clock
        current = msg.clock.sec * 1000000000 + msg.clock.nanosec
        if clock_value is None or current > clock_value:
            last_clock = time.monotonic()
        if clock_value is not None and current < clock_value:
            interrupted.append('simulation_clock_reset')
        clock_value = current

    def feedback(msg):
        f = msg.feedback
        vals = dict(nav_time_sim_s=f.navigation_time.sec + f.navigation_time.nanosec / 1e9,
                    remaining_distance_m=float(f.distance_remaining), recoveries=int(f.number_of_recoveries))
        for key, value in vals.items():
            if math.isfinite(value) and value >= 0:
                metrics.feedback[key] = value
        metrics.feedback['feedback_received_utc'] = ledger.timestamp(ledger.now_utc())

    def tick():
        nonlocal last_checkpoint
        if interrupted:
            raise InterruptedError(interrupted[0])
        if not rclpy.ok():
            raise RuntimeError('ros_context_shutdown')
        now = time.monotonic()
        if now - started >= args.timeout:
            raise TimeoutError('wall_timeout')
        if active and (now - last_clock > args.stale_timeout or now - last_odom > args.stale_timeout):
            raise TimeoutError('simulation_stream_stalled: clock/odom; Gazebo crash is unconfirmed')
        rclpy.spin_once(node, timeout_sec=0.1)
        if now - last_checkpoint >= 1:
            save()
            last_checkpoint = now

    def wait(future):
        while not future.done():
            tick()
        return future.result()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_signals[sig] = signal.signal(sig, lambda signum, frame: interrupted.append(signal.Signals(signum).name))
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        node = rclpy.create_node('navlab_experiment_' + uuid.uuid4().hex[:8],
            parameter_overrides=[Parameter('use_sim_time', value=True)])
        node.create_subscription(Odometry, args.odom, odom, qos_profile_sensor_data)
        node.create_subscription(Clock, '/clock', clock, qos_profile_sensor_data)
        client = ActionClient(node, NavigateToPose, args.action)
        while not client.server_is_ready():
            tick()
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = args.frame
        goal.pose.header.stamp = node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = args.x, args.y
        goal.pose.pose.orientation.z = math.sin(args.yaw / 2)
        goal.pose.pose.orientation.w = math.cos(args.yaw / 2)
        send_future = client.send_goal_async(goal, feedback_callback=feedback, goal_uuid=UUID(uuid=list(action_uuid)))
        handle = wait(send_future)
        if not handle.accepted:
            reason = 'goal_rejected'
        else:
            active = True
            last_odom = last_clock = time.monotonic()
            ledger.checkpoint(rid, {'accepted_utc': ledger.timestamp(ledger.now_utc())})
            result_future = handle.get_result_async()
            result = wait(result_future)
            action_status = result.status
            outcome = outcome_for_status(action_status)
            reason = 'action_result'
            error = getattr(result.result, 'error_msg', '')
            ledger.checkpoint(rid, {'nav2_error_code': getattr(result.result, 'error_code', None)})
    except InterruptedError as exc:
        reason = str(exc)
        # Canceled is only used after server confirms STATUS_CANCELED below.
        error = 'Interrupted; requesting cancellation'
    except Exception as exc:
        reason = str(exc) if isinstance(exc, TimeoutError) else 'ros_or_client_error'
        error = f'{type(exc).__name__}: {exc}'
    finally:
        if node is not None and not rclpy.ok() and reason != 'action_result':
            cancel_state = 'unavailable_ros_context_shutdown_goal_may_still_execute'
        # Bounded cancellation also handles a goal accepted after our send deadline.
        if node is not None and rclpy.ok() and reason != 'action_result':
            until = time.monotonic() + args.cancel_grace
            try:
                while handle is None and send_future is not None and not send_future.done() and time.monotonic() < until:
                    rclpy.spin_once(node, timeout_sec=0.1)
                if handle is None and send_future is not None and send_future.done():
                    handle = send_future.result()
                if handle is not None and handle.accepted:
                    cancel_state = 'requested_unconfirmed'
                    cf = handle.cancel_goal_async()
                    if result_future is None:
                        result_future = handle.get_result_async()
                    while not result_future.done() and time.monotonic() < until:
                        rclpy.spin_once(node, timeout_sec=0.1)
                    if result_future.done():
                        action_status = result_future.result().status
                        cancel_state = 'confirmed' if action_status == 5 else 'terminal_result_received'
                        if interrupted and action_status == 5:
                            outcome = 'canceled'
                    elif cf.done() and not cf.result().goals_canceling:
                        cancel_state = 'rejected'
                elif send_future is not None and not send_future.done():
                    cancel_state = 'acceptance_unknown_goal_may_still_execute'
            except Exception as exc:
                cancel_state = 'cancel_error: ' + str(exc)
        try:
            ledger.finalize(rid, outcome, dict(metrics.values(), action_status=action_status,
                termination_reason=reason, error=error, cancellation=cancel_state,
                duration_wall_s=round(time.monotonic() - started, 3),
                notes_finish=f'auto: {reason}; action_status={action_status}; {error}; cancellation={cancel_state}'))
        finally:
            if node is not None:
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            for sig, previous in old_signals.items():
                signal.signal(sig, previous)
    return 0 if outcome == 'succeeded' else 1
