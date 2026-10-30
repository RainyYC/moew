# 2026-10-29 版题面（problem-v4）适配记录

来源：`problem-v4.md`（用户提供的明文，94 KB；文件里正文出现两次，第二份完整）。
相对上一版（`problem-v3`）有三处实质变化，其余（十种操作、时长公式、内存三块、三档内存核算）不变。

## 1. 网格：`V·P = R` → `V·P ≤ R`

题面 §3.1 原文：

> 网格必须装得进集群：$V\cdot P\le R$。若 $V\cdot P<R$，则只有按上述顺序的前 $V\cdot P$ 张卡承载层，
> 其余 $R-V\cdot P$ 张卡空闲——不执行操作，也不计内存。

**实现**：`_check_grid` 从 `V·P != R` 改成 `V·P > R` 报错；`peer_counts` 去掉 `D` 参数
（`q = v·P + p`）；求解器把 `V` 与 `P` 解耦。

**取哪个 V？** 卡是免费的，加大 `V` 只会让每个卡组少背几层（`lb` 下降），代价是填充项
`(nmb+V−1)/nmb` 略增。两者乘积 `(nmb+V−1)/V` 对 `V` 单调递减 ⇒ **取最大**
`V = min(L, 64, R//P)`。于是每个 `P` 只剩一个候选。

**效果**：`P=1` 时没有 EP 对端、`x=0`，通信整条消失。b01 只用 **64/512** 张卡，
`9.48e14 → 6.89e12`（137 倍）；b05 同理 122 倍。能不能取 `P=1` 完全取决于 `M`。

## 2. 共享专家：与同层其余操作解耦（题面 §4.2 第 1 条原文）

> 路由专家链固定为：前向 `disp → gemm → comb`，反向 `comb_bwd → gemm_dx → disp_bwd`，每一步都排在前一步之后。
> **共享专家不在这两条链上**——`s` 只依赖本层输入（与释放 `disp` 的是同一条边），且须**在 `comb` 之前收尾**；
> `s_bwd` 只依赖送进来的梯度（与释放 `comb_bwd` 的是同一条边；最后一层则看本层自己的 `comb`），
> 且须**在 `disp_bwd` 之前收尾**，因为 `disp_bwd` 要加的梯度里有共享专家那一份。
> 两个权重梯度步骤 `gemm_dw` 与 `s_dw` 只等 `comb_bwd`。
> 两个第一个反向步骤 `s_bwd` 与 `comb_bwd` 都不得早于本层自己的 `comb` 结束。

对应的依赖表（`DEPS`，按操作索引）：

| 操作 | 前驱 |
| --- | --- |
| `s` | — |
| `disp` | — |
| `gemm` | `disp` |
| `comb` | `gemm`, **`s`** |
| `s_bwd` | `comb` |
| `comb_bwd` | `comb` |
| `gemm_dx` | `comb_bwd` |
| `gemm_dw` | `comb_bwd` |
| `disp_bwd` | `gemm_dx`, **`s_bwd`** |
| `s_dw` | `comb_bwd` |

跨层边（§4.2 第 2 条）：`s` 与 `disp` 都等上一层 `comb`；`s_bwd` 与 `comb_bwd` 都等下一层 `disp_bwd`。

### 三处容易写错的地方

1. **`s` 不是自由的**：它必须在 `comb` 之前收尾（`comb ≥ s`）。我第一版把 `s` 完全解耦，
   结果 `ex2` 直接掉到 3200（= 通信下界）——模型退化了。
2. **`disp_bwd` 要等 `s_bwd`**：题面明确"`disp_bwd` 要加的梯度里有共享专家那一份"。
3. **`s_dw` 等的是 `comb_bwd`**，不是 `s_bwd`。

### 之前的错误版本与正确版本对照

| 版本 | ex2 | ex3 | ex5 |
| --- | --- | --- | --- |
| 过度放松（`s` 全解耦、`comb_bwd` 无跨层锚点） | 3200 ❌ | 4000 ❌ | 320 |
| **按题面原文** | **4880** | **6072** | **416** |
| 题面样例 | 4880 | 7000 | 416 |

## 3. 样例输出全部重写

六例的 `SCHEDULE` 都变了（新规则下更优的排法），题面给的 Time 现在是：

| 用例 | 旧样例 | **新样例** | 我们的解 | CP-SAT |
| --- | --- | --- | --- | --- |
| ex1 | 592 | **560** | 560 | OPTIMAL |
| ex2 | 4880 | 4880 | 4880 | OPTIMAL |
| ex3 | 7000 | 7000 | **6072** | OPTIMAL |
| ex4 | 3200 | 3200 | 3200 | OPTIMAL |
| ex5 | 416 | 416 | 416 | OPTIMAL |
| ex6 | 1744 | **1696** | 1696 | OPTIMAL |

**只有 ex3 还有空间**（题面样例 7000，最优 6072，差 13%）。其余五例我们的解已经等于题面样例，
而 CP-SAT 证明它们也都是全局最优——也就是说这次官方给的五份样例本身就是最优解。

## 4. 连带修复

1. 调度器的"入口操作"不再只有 `s`：`disp` 也变成零前驱。初始入堆与窗口门控必须覆盖
   "层 0 上所有零前驱的 base"，否则要么空转死锁、要么绕过窗口让所有 microbatch 同时涌入。
2. 六例样例的 `SCHEDULE` 变了，判题器测试里所有"按行号/时刻"定位的负例锚点都要重挑；
   凡是拿旧样例当夹具的断言（time / movl / comm_first…）都要按新样例重算。
3. `cases/mini` 不再是题面 §3.2 的例子（那一节现在只给前向片段），改成本项目自造的 10 操作最小例，
   Time = 164。

## 5. 复现

```bash
python3 -m judge.core.acceptance        # 7/7（样例 Time 与新期望一致）
python3 -m judge.service.selftest       # 23/23
python3 -m unittest discover -s judge/tests -q          # 66 OK
python3 -m unittest discover -s solver/selftests -t . -q # 8 OK
python3 solver/solve_all.py --check     # 560/4880/6072/3200/416/1696
python3 scripts/e2e.py                  # 17 PASS / 0 FAIL / 1 SKIP
PYTHONPATH=.pylibs python3 tools/cpsat_global.py cases/ex3.in   # 6072 · OPTIMAL
```
