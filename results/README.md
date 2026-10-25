# 实验结果目录

- `summary.csv`：小型汇总表，建议纳入 Git；每行对应一条经人工确认的实验结果。
- `runs/<run_id>/run.json`：每次实验的详细清单（开始时创建、结束时更新）；目录建议默认由 Git 忽略，不把大量原始日志上传到 GitHub。
- Gazebo/ROS 2 原始启动日志目前仍由现有 `scripts/start_navigation.sh` 记录到 `~/turtlebot4_ws/log/navlab/`；可以在 `experiment_log.py start --launch-log <绝对路径>` 中建立关联，不要重复保存大型日志。

**字段说明**：`duration_wall_s` 为记录脚本启动到登记结束的现实时间，不等于真正的 Nav2 导航耗时。`nav_time_sim_s` 填 RViz/导航反馈显示的任务耗时（如记录时观察到的值），不能拿现实墙钟时间代替。`gazebo_rtf=0.4` 代表 40% 实时因子。没有测量的碰撞次数或路径长度留空，不能用 0 代替未知。`outcome` 只能是 `succeeded`、`failed`、`canceled`，取消不算成功。

**数据解释**：首次成功的 19 秒、0.03 米、恢复 1 次属于历史单次演示，除非有完整的 trial 起点、目标及协议，不要混入未来的定量基线统计。
