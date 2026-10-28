# 局部控制器对比

在同一个起点、同一套目标、同一份参数文件上，只替换 Nav2 的局部控制器（`controller_server` 的 `FollowPath` 插件），看三种控制律在同一批任务上的差别。

[返回首页](../README.md) · [官方基线结果](baseline.md) · [目标集与难度定义](goal_set.md)

## 方法

三份参数文件由脚本从 `turtlebot4_navigation` 的 `nav2.yaml` 生成，**除 `controller_server` 的 `FollowPath` 块之外逐字段一致**（已用 YAML 深度比对验证）。因此三臂之间唯一的变量就是控制律。

| 臂 | 插件 | 参数来源 |
| --- | --- | --- |
| `mppi` | `nav2_mppi_controller::MPPIController` | 上游配置原文，未改 |
| `rpp` | `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController` | 插件默认值，仅把速度上限对齐 |
| `graceful` | `nav2_graceful_controller::GracefulController` | 插件默认值，仅把速度上限对齐 |

三臂的速度上限统一为 **0.5 m/s**（上游 MPPI 的 `vx_max`），避免把"谁默认跑得快"误当成"谁控制得好"。

其余条件与官方基线完全相同：固定起点 `S0 = map (0, 0, 0)`、8 个目标、每次试验前重启整套仿真、试验前跑 `scripts/check_paths.py` 自检。

## 结果

每个目标一次试验（`TRIALS=1`）。单元格为「导航耗时（仿真时间）/ 恢复次数」。

| 目标 | 类别 | 规划路径 | MPPI | RPP | Graceful |
| --- | --- | --- | --- | --- | --- |
| G01 | simple | 7.88 m | 49.7 s / 3 | 59.5 s / 3 | 42.4 s / 1 |
| G02 | simple | 7.57 m | 31.5 s / 0 | 30.4 s / 0 | 31.6 s / 0 |
| G03 | turning | 24.78 m | 136.7 s / 5 | 127.1 s / 4 | 126.0 s / 4 |
| G04 | turning | 24.23 m | 174.3 s / 8 | 171.2 s / 8 | **138.2 s / 5** |
| **G05** | **narrow** | **26.31 m** | **成功 176.5 s / 7** | **失败** | **失败** |
| G06 | narrow | 8.28 m | 39.9 s / 0 | 33.6 s / 0 | 36.3 s / 0 |
| G07 | long | 42.57 m | 194.3 s / 4 | 201.7 s / 4 | 201.4 s / 6 |
| G08 | long | 39.82 m | 187.7 s / 4 | 182.4 s / 3 | 176.9 s / 3 |

只在三个臂都成功的目标上取平均（G01–G04、G06–G08 共 7 个）。如果把只有 MPPI 通过的 G05 也算进 MPPI 的平均，就成了用不同的目标集比较，结论会失真。

| 臂 | 成功率 | 共同目标上的平均耗时 | 平均恢复次数 |
| --- | --- | --- | --- |
| MPPI | 8 / 8 | 116.3 s | 3.43 |
| RPP | 7 / 8 | 115.1 s | 3.14 |
| Graceful | 7 / 8 | **107.6 s** | **2.71** |

## 结论

**1. 只有 MPPI 能通过 0.55 m 的窄通道（G05）。**

RPP 在中途放弃，剩余距离 24.35 m（规划 26.31 m），即净前进约 **2 m**，里程计却累计走了 20.76 m —— 说明它在原地附近反复摆动，触发 15 次恢复后中止。Graceful 走得更远（净前进约 **8.3 m**），但恢复次数更多（19 次）才放弃。

这条目标是整组实验里唯一能区分三个控制器的场景。此前 24 次基线试验全部成功、没有任何区分度，正是因为目标集里缺少对控制律敏感的任务。

**2. 在转弯路线上 Graceful 明显更省。**

G04：138.2 s / 5 次恢复，对比 MPPI 174.3 s / 8 次 —— 耗时低 **21%**，恢复次数少 **37%**。G03 上三者接近（126–137 s），差距在噪声量级。

**3. 简单与短距离目标上三者没有区别。**

G02 三者 30.4–31.6 s、恢复次数全部为 0；G06 33.6–39.9 s、同样全部为 0。差异只出现在特定场景，不存在"某个控制器全面更好"。

## 局限

- **每个目标只有一次试验。** 上表的差异是存在的，但单次样本无法给出波动范围。要做统计结论需要每目标 3 次以上。
- **RPP 与 Graceful 未调参。** 两者都用插件默认值，只对齐了速度上限。RPP 的 `lookahead_dist` 为 0.6 m，比 G05 的 0.55 m 瓶颈还宽，切角是它卡住的合理原因之一；调过参数的 RPP 未必如此。因此不能把 G05 的失败直接解读为"RPP 不适合窄通道"，只能说"默认参数下的 RPP 不适合"。
- **恢复次数只是次数**，不含恢复类型（清代价地图 / 旋转 / 后退），也未采集碰撞数据（自动记录没有可靠来源，见 [实验记录](experiment_logging.md)）。
- 只在 warehouse 场景、DiffDrive 底盘、0.5 m/s 速度上限下成立，换场景或速度需要重测。

## 复现

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab

# 三个臂各跑一遍，每次跑完自动归档到 results/archive/ctl_<arm>/
./scripts/run_controller_matrix.sh

# 单独跑某一臂
CONTROL=rpp TRIALS=1 ./scripts/run_batch.sh

# 并排对比
/usr/bin/python3 scripts/compare_arms.py \
  mppi=results/archive/ctl_mppi/runs \
  rpp=results/archive/ctl_rpp/runs \
  graceful=results/archive/ctl_graceful/runs
```

启动时 `scripts/start_navigation.sh` 会打印当前生效的控制臂，运行中可用 `ros2 param get /controller_server FollowPath.plugin` 确认。
