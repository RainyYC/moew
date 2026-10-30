# 固定布局下的窗口扫描

在保持每个 case 的 final V/P/K/PSI/MAP 和层时长不变的条件下，用 `event_scheduler.hpp` 扫描窗口 `W=1..nmb`（这五案 `nmb≤64`），mode 0/1/2，以及生产式自动通信预算和正通信组全 b=1。自动策略为：若 b=2 后仍能预约至少 `n_g` 个激活额度则选 b=2，否则 b=1；全零通信组用 b=0。每种配置均使用生产相同的预约公式和额度截断。每案都在 10 秒上限内完成，未触顶。

| Case | Final Time | 最佳扫描 Time | W | Mode | Buffer 策略 | 官方验收 |
|---|---:|---:|---:|---:|---|---|
| x16_vl_trap4_ramp | 4,274,914 | 4,274,914 | 16 | 0 | 自动 | 与 final 持平 |
| x17_vl_tight_block | 6,055,940 | 6,010,628 | 31 | 0 | 自动 | 通过 |
| x18_vl_tight_small | 1,792,964 | 1,792,964 | 8 | 0 | 自动 | 与 final 持平 |
| x20_vl_flat_control | 2,443,667 | 2,407,088 | 30 | 0 | 全 b=1 | 通过 |
| r64_v8_c8a | 5,282,831 | 5,282,831 | 25 | 0 | 自动 | 与 final 持平 |

仅 `x17_vl_tight_block` 和 `x20_vl_flat_control` 得到更短结果，分别改善 45,312 和 36,579 时间单位；两者均由官方 grader 确认合法且 Time 匹配。三种调度 mode 中最佳都是 mode 0。其余三案扫描没有超过 final。

驱动与重现实验脚本为 `window_probe.cpp`、`run_window_probe.py`；机器可读记录在 `window_probe.json`。候选输出仅写入本目录，没有覆盖 `results/final`，未改生产代码。
