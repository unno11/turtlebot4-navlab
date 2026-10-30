#!/usr/bin/env python3
"""Train a behaviour-cloning policy on collected demonstrations.

Split is temporal and per file: the tail of every demonstration is held out, so
the validation loss reflects "later in the same run", not a different goal.

    ~/venvs/navlab-il/bin/python scripts/train_bc.py \
        --demos results/demos --out results/policy/bc_policy.npz
"""

import argparse
import glob
import json
import os

import numpy as np
import torch
from torch import nn


def load_demos(demo_dir, val_frac, include=None):
    files = sorted(glob.glob(os.path.join(demo_dir, "*.npz")))
    if include:
        keys = [k.strip() for k in include.split(",") if k.strip()]
        files = [f for f in files if any(k in os.path.basename(f) for k in keys)]
    if not files:
        raise SystemExit(f"no demonstrations under {demo_dir}" + (f" matching {include}" if include else ""))
    tr_obs, tr_act, va_obs, va_act, report = [], [], [], [], []
    for f in files:
        d = np.load(f)
        obs, act = d["obs"], d["act"]
        n = len(obs)
        cut = max(1, int(n * (1.0 - val_frac)))
        if n < 50:
            report.append({"file": os.path.basename(f), "samples": n, "used": False})
            continue
        tr_obs.append(obs[:cut])
        tr_act.append(act[:cut])
        va_obs.append(obs[cut:])
        va_act.append(act[cut:])
        report.append({"file": os.path.basename(f), "samples": n, "train": cut, "val": n - cut, "used": True})
    if not tr_obs:
        raise SystemExit("every demonstration was too short to use")
    return (np.concatenate(tr_obs), np.concatenate(tr_act),
            np.concatenate(va_obs), np.concatenate(va_act), report)


def build_model(obs_dim, act_dim, hidden):
    return nn.Sequential(
        nn.Linear(obs_dim, hidden), nn.ReLU(),
        nn.Linear(hidden, hidden), nn.ReLU(),
        nn.Linear(hidden, act_dim),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demos", default="results/demos")
    ap.add_argument("--include", default=None, help="comma-separated filename filters, e.g. G01,G02")
    ap.add_argument("--out", default="results/policy/bc_policy.npz")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    tr_obs, tr_act, va_obs, va_act, report = load_demos(args.demos, args.val_frac, args.include)
    obs_mean, obs_std = tr_obs.mean(0), tr_obs.std(0) + 1e-6
    act_mean, act_std = tr_act.mean(0), tr_act.std(0) + 1e-6
    print(f"train {tr_obs.shape}  val {va_obs.shape}  files {sum(1 for r in report if r.get('used'))}")

    x = torch.tensor((tr_obs - obs_mean) / obs_std, dtype=torch.float32)
    y = torch.tensor((tr_act - act_mean) / act_std, dtype=torch.float32)
    xv = torch.tensor((va_obs - obs_mean) / obs_std, dtype=torch.float32)
    yv = torch.tensor((va_act - act_mean) / act_std, dtype=torch.float32)

    model = build_model(tr_obs.shape[1], tr_act.shape[1], args.hidden)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss()
    n = len(x)
    best = float("inf")
    best_state = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, args.batch):
            idx = perm[i:i + args.batch]
            opt.zero_grad()
            loss = loss_fn(model(x[idx]), y[idx])
            loss.backward()
            opt.step()
            total += float(loss) * len(idx)
        if epoch % 20 == 0 or epoch == args.epochs:
            model.eval()
            with torch.no_grad():
                vl = float(loss_fn(model(xv), yv))
            if vl < best:
                best, best_state = vl, {k: v.detach().clone() for k, v in model.state_dict().items()}
            print(f"epoch {epoch:4d}  train {total / n:.4f}  val {vl:.4f}")

    if best_state is not None:
        model.load_state_dict(best_state)

    # Export plain numpy weights: deployment then needs no torch at all.
    model.eval()
    linears = [m for m in model if isinstance(m, nn.Linear)]
    arrs = {}
    for i, layer in enumerate(linears, start=1):
        w = layer.weight.detach().numpy().T.astype(np.float64)
        arrs[f"w{i}"] = w
        arrs[f"b{i}"] = layer.bias.detach().numpy().astype(np.float64)
    arrs.update(obs_mean=obs_mean, obs_std=obs_std, act_mean=act_mean, act_std=act_std)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    np.savez(args.out, **arrs)

    model.eval()
    with torch.no_grad():
        pred = model(xv).numpy() * act_std + act_mean
    mae = np.abs(pred - va_act).mean(0)
    summary = {
        "samples_train": int(len(x)), "samples_val": int(len(xv)),
        "val_mse_normalised": round(best, 5) if best != float("inf") else None,
        "val_mae": {"v": round(float(mae[0]), 4), "w": round(float(mae[1]), 4)},
        "act_std": {"v": round(float(act_std[0]), 4), "w": round(float(act_std[1]), 4)},
        "files": report,
    }
    with open(os.path.splitext(args.out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}  val MAE v={mae[0]:.3f} m/s  w={mae[1]:.3f} rad/s")


if __name__ == "__main__":
    main()
