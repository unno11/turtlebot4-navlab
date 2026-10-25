# 实验结果目录

本目录保存工具输出格式的说明。**每次运行的结果仅保留在本地，不纳入 Git。**

[如何记录实验](../docs/experiment_logging.md) · [返回首页](../README.md)

## 文件位置

| 文件 | 用途 | Git 跟踪 |
| --- | --- | --- |
| `summary.example.csv` | 仅含表头的格式模板，无真实或模拟数据行 | 是 |
| `summary.csv` | 本地任务汇总，每个结束的 run 对应一行 | 否 |
| `runs/<run_id>/run.json` | 单次任务详情、状态和采集指标 | 否 |
| `.experiment.lock` | 记录工具的并发写入锁 | 否 |

工具会按需创建本地 JSON 和汇总文件，无需手工复制模板。Gazebo / ROS 启动日志由启动脚本保存在 `~/turtlebot4_ws/log/navlab/`；可用 `--launch-log` 关联，无需重复保存大型日志。

## 字段说明

`summary.csv` 的列保持固定。JSON `null` 对应 CSV 空单元格，表示未知，不等于零。

| 字段 | 含义 |
| --- | --- |
| `run_id` | 单次记录的唯一 ID，不重复写入汇总 |
| `goal_id` / `trial` | 目标标签 / 试验序号 |
| `outcome` | succeeded、failed 或 canceled；取消不算成功 |
| `started_utc` / `finished_utc` | 记录起止 UTC 时间 |
| `duration_wall_s` | 记录开始到结束的现实秒数，包含等待和取消宽限；自动采集使用 monotonic，手工结束使用 UTC 起止差 |
| `nav_time_sim_s` | 导航反馈中的仿真耗时；手工模式填写实际观察值，不能用墙钟替代 |
| `remaining_distance_m` | 最后反馈或人工确认的剩余距离，米 |
| `recoveries` | 反馈中的恢复次数，或人工确认值 |
| `collisions` | 真实碰撞计数；自动模式当前无可靠来源，保持未知 |
| `path_length_m` | 自动模式为 odom 相邻位置累加的平面路径估计，非 Ground Truth；样本不足或数据无效时未知 |
| `gazebo_rtf` | 实时因子，0.4 表示 40%；自动模式当前无可靠来源 |
| `git_commit` | 创建记录时的 Git HEAD |
| `launch_log` / `notes` | 关联日志路径 / 补充说明和异常原因 |

自动反馈指标是最后收到的样本，不保证恰好对应终态。JSON 还保存原始 `action_status`、Action UUID、目标位姿、终止原因、取消确认、来源和 heartbeat。未收到 Action 终态时状态为 null；实验 failed 不代表服务器一定返回 aborted。

## 数据保存原则

- `start` / `finish` 与 `navigate` 共用同一格式，不维护两张不兼容的表。
- JSON 和 CSV 使用文件锁与原子写入；已结束 JSON 缺少汇总行时使用 `recover`。
- 原始记录和真实汇总被 `.gitignore` 排除，不要使用 `git add -f` 强行提交。
- 本地记录应另行备份；不要为清理版本库而删除实验历史。
- 模拟测试只写临时目录；单次演示与测试成功都不能代替正式基线统计。
