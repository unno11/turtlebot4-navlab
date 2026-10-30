#!/usr/bin/env python3
"""Feature and policy definitions shared by collection, training and deployment.

The observation layout is defined once, here, so that a policy trained on
collected data cannot silently disagree with the node that later runs it.
"""

import numpy as np

# Observation layout (do not reorder without retraining):
#   [0:N_BINS]      laser ranges, min-pooled, clipped, normalised
#   [-4]            lookahead point, x in base_link
#   [-3]            lookahead point, y in base_link
#   [-2]            distance to goal, metres
#   [-1]            last commanded yaw rate
N_BINS = 60
OBS_DIM = N_BINS + 4
ACT_DIM = 2
RANGE_MAX = 6.0
LOOKAHEAD = 0.7
V_MAX = 0.5
W_MAX = 1.0


def bin_scan(ranges, n_bins=N_BINS, range_max=RANGE_MAX):
    """Min-pool a LaserScan into n_bins, clipped and normalised to [0, 1]."""
    r = np.asarray(ranges, dtype=np.float32)
    if r.size == 0:
        return np.ones(n_bins, dtype=np.float32)
    r = np.where(np.isfinite(r), r, range_max)
    r = np.clip(r, 0.0, range_max)
    # A scan is counter-clockwise from -pi to +pi; pooling preserves that order.
    edges = np.linspace(0, r.size, n_bins + 1).astype(int)
    out = np.empty(n_bins, dtype=np.float32)
    for i in range(n_bins):
        lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
        out[i] = r[lo:hi].min()
    return out / range_max


def lookahead_point(path_xy, robot_xy, lookahead=LOOKAHEAD):
    """Return the point on the path roughly `lookahead` metres ahead of the robot.

    path_xy is an (N,2) array in the map frame. Returns (point, remaining_distance)
    where point is None when the path is empty.
    """
    if path_xy is None or len(path_xy) == 0:
        return None, float("inf")
    p = np.asarray(path_xy, dtype=np.float64)
    d = np.linalg.norm(p - np.asarray(robot_xy, dtype=np.float64), axis=1)
    i = int(np.argmin(d))
    remaining = float(np.sum(np.linalg.norm(np.diff(p[i:], axis=0), axis=1)))
    acc = 0.0
    j = i
    while j < len(p) - 1 and acc < lookahead:
        acc += float(np.linalg.norm(p[j + 1] - p[j]))
        j += 1
    return p[j], remaining


def to_base_frame(point_xy, robot_xy, yaw):
    """Express a map-frame point in the robot base frame."""
    dx = point_xy[0] - robot_xy[0]
    dy = point_xy[1] - robot_xy[1]
    c, s = np.cos(yaw), np.sin(yaw)
    return c * dx + s * dy, -s * dx + c * dy


def build_obs(ranges, path_xy, robot_xy, yaw, goal_xy, w_prev):
    """Assemble one observation vector. Returns obs and a bool for validity."""
    scan = bin_scan(ranges)
    point, remaining = lookahead_point(path_xy, robot_xy)
    if point is None:
        lx, ly = 0.0, 0.0
    else:
        lx, ly = to_base_frame(point, robot_xy, yaw)
        lx = float(np.clip(lx, -5.0, 5.0))
        ly = float(np.clip(ly, -5.0, 5.0))
    d_goal = float(np.linalg.norm(np.asarray(goal_xy, dtype=np.float64) - np.asarray(robot_xy, dtype=np.float64)))
    obs = np.concatenate([scan, np.array([lx, ly, min(d_goal, 60.0), w_prev], dtype=np.float32)])
    return obs.astype(np.float32)


def clip_action(v, w, v_max=V_MAX, w_max=W_MAX):
    return float(np.clip(v, -v_max, v_max)), float(np.clip(w, -w_max, w_max))


class Policy:
    """Two-hidden-layer MLP evaluated with numpy, so deployment needs no torch."""

    def __init__(self, path):
        d = np.load(path)
        self.w = [d["w1"], d["w2"], d["w3"]]
        self.b = [d["b1"], d["b2"], d["b3"]]
        self.obs_mean = d["obs_mean"]
        self.obs_std = d["obs_std"]
        self.act_mean = d["act_mean"]
        self.act_std = d["act_std"]

    def __call__(self, obs):
        x = (np.asarray(obs, dtype=np.float64) - self.obs_mean) / self.obs_std
        for i, (w, b) in enumerate(zip(self.w, self.b)):
            x = x @ w + b
            if i < len(self.w) - 1:
                x = np.maximum(x, 0.0)
        act = x * self.act_std + self.act_mean
        return clip_action(act[0], act[1])
