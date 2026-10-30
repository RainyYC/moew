# 退化形态自测（`solver/selftests/`）

任务书要求：**V=1、L=1、P=1 零通信、x=0、s=0、R=1、nmb=2** 每种退化形态至少有 1 个
**自造**用例可解、且被 `python3 -m judge eval` 判定合法。这些输入不是题面样例，是为了把
求解器逼到退化分支而构造的（形态越极端，越容易暴露「只在常规形状下正确」的假设）。

| 用例 | 覆盖形态 | 构造要点 | 期望现象 |
| --- | --- | --- | --- |
| `v1_l1.in` | **V=1**、**L=1** | `L=1` 时 `V≤L` 只剩 `V=1`；`R=4`、`E=4`、`P=4` 可解 | PSI 行只有块数 `1`（**空切点**） |
| `p1_zero_comm.in` | **P=1** 零通信、**x=0** | `E=3` 为质数且 `R=2`，`P∣E` 与 `P∣R` 只剩 `P=1`；EP 组没有对端 ⇒ `X=0, x=0` | 通信类操作全部 0 时长 |
| `x0_zero_payload.in` | **x=0**、**s=0** | 所有层 `T=0` ⇒ `X=0`、`m=0`；`Fs` 非零但乘出来仍是 0 | **全部操作 0 时长，Time=0**（同时刻大量合并行） |
| `s0.in` | **s=0** | `Fs=0` ⇒ `s = s_bwd = s_dw = 0`，但 `gemm` 非零 | 计算引擎只被 `gemm` 系列占住 |
| `r1.in` | **R=1** | `N=S=1` ⇒ `R=1` ⇒ `V=P=D=1`；`L=2` | 单卡、单 stage、`P=1` 零通信 |
| `nmb2.in` | **nmb=2**、V=2 | 两层分别落到两个卡组，`nmb=2` 让流水线有两条时间线 | 两个卡组的操作交错 |

## 运行

```bash
python3 solver/selftests/run.py            # 逐个求解 + `python3 -m judge eval` 复核 + 形态断言
python3 solver/selftests/run.py --quiet    # 只打印结论
python3 solver/selftests/run.py --no-judge # 只跑求解（调试用，不作为验收证据）
```

`run.py` 会：

1. 读取本目录每个 `*.in`，用 `solver.solve.solve_case` 求解，输出写同名的 `*.out`（**已交付**，
   便于直接复现/复核）；
2. 调 `python3 -m judge eval <in> <out> --json`（`solver/judgedbridge.py`，子进程，不 import
   `judge.core`）确认 `ok:true`；
3. 核对 **求解器自算 Time == judge 判定 Time**（两套独立实现的一致性证据）；
4. 断言输出确实落在该用例预期的退化形态上（例如 `r1` 必须是 `(V,P,D)=(1,1,1)`，
   `x0_zero_payload` 必须是 `Time=0`）。

全部通过时退出码 0；任何一项失败打印明细并退出 1。`python3 solver/solve_all.py --check`
会把它作为退化形态门禁一起跑。
