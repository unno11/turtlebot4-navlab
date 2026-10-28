# TurtleBot 4 NavLab

ROS 2 Jazzy · Gazebo Harmonic · TurtleBot 4 · Nav2

[![CI](https://github.com/unno11/turtlebot4-navlab/actions/workflows/ci.yml/badge.svg)](https://github.com/unno11/turtlebot4-navlab/actions/workflows/ci.yml)

基于官方 warehouse 场景的移动机器人导航基线：固定起点、8 个经规划器复核的目标、24 次重复试验。目的是得到可重复的量化结果，而不是单次演示。

![NavLab 导航演示](docs/media/navlab-demo.gif)

*RViz 中的一次导航过程（约 6 分钟实时，24 倍速压缩）。红色为 Nav2 规划的全局路径，左下角为实时状态：剩余距离、已用时间、恢复次数。*

## 结果

| 项目 | 内容 |
| --- | --- |
| 场景 | Gazebo `warehouse`，AMCL 定位，`turtlebot4_navigation` 默认参数未做修改 |
| 起点 | `S0 = map (0, 0, 0)`，每次启动自动注入 |
| 目标 | 8 个，按实际规划路径分为 simple / turning / narrow / long |
| 试验 | 每目标 3 次，共 24 次，每次试验前重启整套仿真 |
| 成功率 | 24 / 24 |
| 单次导航耗时 | 29–205 s（仿真时间） |

指标定义与逐目标结果见 [官方基线结果](docs/baseline.md)。同一批目标上只替换局部控制器的对比结果见 [局部控制器对比](docs/controller_comparison.md)。

## 快速开始

```bash
cd ~/turtlebot4_ws/src/turtlebot4-navlab
./scripts/start_navigation.sh                    # Gazebo + Nav2 + AMCL，起点自动固定为 S0
TRIALS=3 ./scripts/run_batch.sh                  # 8 个目标 x 3 次，逐个重启、自检、记录
/usr/bin/python3 scripts/summarize_results.py    # 生成结果表
```

环境要求见 [复现与启动指南](docs/reproduction.md)。起点由 `config/localization.yaml` 固定，无需使用 RViz 的 2D Pose Estimate。

## 四个排障记录

下面四处是真正花时间的地方。写的是现象、查了什么、哪条证据改变了判断 —— 不是整理好的结论，是能照着复盘的记录。

### 1. 起点每次都不一样

**现象**：想在每次试验用同一个起点，但起点是靠在 RViz 里拖 2D Pose Estimate 给的。同一台机器拖两次会得到两个不同的值，`map → base_link` 也就跟着变；没有任何依据说明哪个是对的。

**查了什么**：先确认这不是 TF 配置问题 —— `map → odom` 由 AMCL 发布，`odom → base_link` 由底盘发布，链路本身正常，问题只在 AMCL 的初始位姿来自人手。

**什么证据改变了判断**：取一帧 `/scan`，沿 URDF 链条（`base_link → shell_link → rplidar_link`，注意雷达的 rpy 是 `0 0 π/2`，0° 不对着车头）变换到车体系，再与 `warehouse.pgm` 的距离变换做拟合。`(0, 0, 0)` 的平均残差 **0.012 m**；手拖的 `(-0.094, -0.122, -3.122)` 残差 **3.14 m**，yaw 差了约 180°。差一个车身，不是误差范围内的事。

**结论**：起点是 `(0, 0, 0)`，写进 `config/localization.yaml` 的 `initial_pose`，启动时注入 AMCL。同时接受一个限制：这是拿一帧激光拟合出来的，不是标定，换地图或换世界必须重测。

### 2. 目标难度不能凭坐标猜

**现象**：最初按"坐标看起来远不远"给目标分难度，但 G01 直线距离只有 0.65 m，G07 有几十米 —— 这两者之间的差别根本不在同一个维度上。

**查了什么**：让 Nav2 规划器把 8 个目标逐个实际规划一遍，记录路径长度、累计转角、转角密度、最窄通行宽度。

**什么证据改变了判断**：规划出来的累计转角与坐标距离并不同序 —— 有的目标很近但要绕一大圈。分类只能按规划结果给，不能按坐标。

**结论**：四类（simple / turning / narrow / long）由实测数据划分，判据固化在 `scripts/check_paths.py`，每次实验前先跑一遍，任一项偏离基线就中止 —— 防止环境漂移悄悄污染整批数据。

### 3. 24 次试验怎么保证是同一件事

**现象**：手工点 24 次不可靠；更麻烦的是第一批数据里混进了"被墙钟超时打断"的记录，它们看起来像失败，其实根本没形成导航结果。

**查了什么**：逐条看 `run.json` 的 `termination_reason` 与 `action_status`。

**什么证据改变了判断**：一条 `outcome=failed` 的记录，`action_status` 是 5 或空、`termination_reason` 是 `wall_timeout` —— 动作压根没返回最终状态。按 `outcome` 直接统计会把工具问题算成算法问题。

**结论**：判据改成只看"动作有没有返回最终状态"，实现集中在 `scripts/run_record.py`，汇总脚本和批量脚本共用；每次试验之间重启整套仿真，保证出生位姿与 AMCL 初始位姿回到同一状态。

### 4. 24/24 全成功，说明不了任何事

**现象**：基线 24 次试验全部成功。这是好事，但它意味着这个测试集对 Nav2 默认参数没有任何区分度 —— 拿它去比较任何改动，都只能得到"都是 100%"。

**查了什么**：把局部控制器换成三个（MPPI / RPP / Graceful），只替换 `controller_server` 的 `FollowPath` 插件，三份参数文件经解析后逐字段比对，确认只有这一块不同；速度上限统一到 0.5 m/s。

**什么证据改变了判断**：G05（0.55 m 窄通道）出现差异 —— MPPI 完成，RPP 净前进约 2 m 后中止，Graceful 约 8 m 后中止。但接着查日志发现，同一次运行里 `diffdrive_controller` 丢弃过期速度指令的告警数分别是 **41 / 36 / 82** 条：MPPI 在告警更多的情况下仍然完成，所以不能简单说"丢指令导致失败"，也无法排除 RPP / Graceful 是被丢指令拖垮的。每个臂只有一次运行。

**结论**：**差异存在，原因未确立。** 早先版本把原因写成"RPP 的前视距离 0.6 m 比通道 0.55 m 宽"，这是错的 —— 前视距离是沿路径的弧长，通道宽度是横向尺度，量纲不同不能直接比。要判断得在 RTF ≥ 0.5 的宿主上重跑或做多次重复。完整数据、宿主速度差异与全部局限见 [局部控制器对比](docs/controller_comparison.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [复现与启动](docs/reproduction.md) | 首次运行、环境检查、确认初始定位、发送目标、退出仿真 |
| [目标集与难度定义](docs/goal_set.md) | 8 个导航目标、难度判据与复核方法 |
| [官方基线结果](docs/baseline.md) | 基线条件、结果表、指标口径与复跑方式 |
| [局部控制器对比](docs/controller_comparison.md) | MPPI / RPP / Graceful 在同一批目标上的对比与结论 |
| [实验记录](docs/experiment_logging.md) | 自动记录流程、结果分类规则、仿真速度门禁 |
| [结果目录](results/README.md) | 输出位置、字段含义与本地数据管理 |
| [环境排障](docs/troubleshooting.md) | 图形、雷达、TF、控制器或构建问题 |

## 环境

- Ubuntu 24.04 / WSL2
- ROS 2 Jazzy
- Gazebo Harmonic
- TurtleBot 4 Simulator
- Nav2

已验证的版本与检查命令见 [环境要求](docs/reproduction.md#环境要求)。启动脚本包含 NVIDIA D3D12 相关设置，面向 WSL2 环境；其他显卡或原生 Linux 环境需要单独验证。

## 数据与版本库

原始运行数据（`results/runs/`、`summary.csv`、批量日志）不纳入版本库，`results/` 只保留说明文档与表头模板 `summary.example.csv`。历史批次归档在同一目录下，可用 `scripts/summarize_results.py --runs <目录>` 重新生成对应结果表。

## 上游项目

- [turtlebot/turtlebot4_simulator](https://github.com/turtlebot/turtlebot4_simulator)
- [ros-navigation/navigation2](https://github.com/ros-navigation/navigation2)
