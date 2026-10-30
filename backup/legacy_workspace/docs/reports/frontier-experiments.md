# frontier t4：同配置消融与同预算端到端实验

> 状态：**探索结论，候选默认关闭**。正式 50/13/留出集在 t5 独立验收。
> 口径见 `docs/reports/frontier-protocol.md`（v1）与 `docs/reports/frontier-baseline.md`（t3）。
> 本文所有数字来自 `runs/frontier/experiments/t4*/` 与 `runs/frontier/experiments/t4-e2e/`。

---

## 0. 结论先行

1. **等价性成立，但不是“加速”**：`order="lazy_early"` 与基线 `early` 在 28 个可测例上
   Time **逐例相同**，`order="priority"` 与 `prio` 在 31 例上逐例相同；这两个替身仍会
   惰性重入堆。真正快的是 `order="time"`，但它是**不同派发规则**（16 好 / 4 差 / 8 平），
   且真实构造墙钟并非全面更快：<2k op 中位 3.56×、2k–20k 1.81×、20k–100k 0.87×。
   **不声称训练加速**；t2 的“40k 21.9s→0.30s”是计数包装器开销，已从报告中撤回。
2. **零时长零等待是语义修正，无 Time 收益**：`zero_free` 两态在 31/31 例 Time 相同
   （即使 ex2/ex5 上零时长操作确实提前了 24–32 个时间单位）。
3. **生命周期门控在本次探索中没有绑定**：31 例的 `gating_binding=0`；B 相对 A 的差异
   来自“去窗口 + 默认剩余路径优先级 + 候选集”，**不能归因于门控**。只有受控合成例
  （`cap_act=3`、相邻层）上门控相对整数窗口 298→288（−3.4%）体现机制收益。
4. **B 独立替换基线没有稳定收益**：11 好 / 13 差 / 6 平；fast12 7/2/3（合计 −0.148%），
   K=2V 6 例 3/3（合计 +1.54%），samples 0/4/2，battery5 1/4/0（合计 −2.1% 由 b13 单例
   驱动，其余 4 例更差）。**C（一步偏离+贪心 rollout）相对 B 3 好/0 差/25 平，仍不及基线**。
5. **端到端（ABBA，2 趟/臂）**：fast12 6 好/1 差/5 平（−0.186%），其中 r24 的“差”
   是墙钟截断离群（5 次候选重复里 4 次优于 fullB，详见 §5.3）；K=2V 6 例 3 好/0 差/3 平
   （−0.98%）；samples 全平；battery5 全平（frontier 在 5/5 例 `stop=deadline`、无命中）。
   **no-op 控制臂**（只预留、不运行）在 r24×3、r32×1 上与 fullB 完全相同，说明预留预算
   本身在这些病例没有系统性代价；r24 的离群来自截断选到不同配置。
6. **启用建议**：候选在 fast12/K=2V 有可复现的小幅收益、无稳定回归，但电池/样例无收益，
   正式 50/13/留出集未验；**t4 仍保持默认关闭**，交 t5 决定是否默认启用。

---

## 1. 冻结版本与参数

| 项 | 值 |
| --- | --- |
| worktree | `/home/rainy/hackathon/work-frontier-sgs`（分支 `opt-frontier-sgs`） |
| 候选代码版本 | `83638d07edc983f98dae8878b763efb7dc4eae17`（t4 冻结；本文档为后续 docs commit） |
| 生产接口 | `solve_all.py <case> <out>` 不变；`--frontier` 显式启用，默认关闭 |
| frontier 参数 | `mode=B`（候选臂）/`C`（消融）；`policy="auto"`；`zero_free=True`；`gating=True`；`window=None`；`seed=20261020` |
| 接入参数 | `frontier_reserve = min(0.9s, max(0.4s, 0.12·B))`；`n_ops≤20k` 扫 `VARIANTS[0,2,4,5,7]`×`{auto,comm1}`，`>20k` 扫 `VARIANTS[0,4]`×`{auto}`；仅接受严格更优且 `memory_usage` 通过的解 |
| 对照工具 | `tools/frontier_bench.py`（t6 版 `ac50a09`）与 `tools/frontier_ablate.py` |
| 候选入口 | `tools/frontier_candidate.py`（显式 `--frontier`，供 bench 调用） |
| 固定配置 | t3 冻结基线输出 `runs/frontier/baseline/{baseline-official50,baseline-samples7,baseline-battery13,mini-even}` |

**禁止**：不改 fill_boost / 逐引擎序列 ILS / placement / psi；不按用例名特判；不新增生产依赖；
不把超过 10s 的搜索当可提交结果；本文件不覆盖 t3 原始基线记录。

---

## 2. 对照臂

| 臂 | 定义 | 用途 |
| --- | --- | --- |
| `fullB` | 冻结基线 worktree `c558d9b` 的 `solve_all.py`，同显式预算 | ABBA 主对照（T_fullB） |
| `B` | sgs 候选入口 `frontier_candidate.py`（`--frontier --frontier-mode B`） | 候选净收益 |
| `noop` | 候选入口 `--frontier-mode noop`：同样预留预算，但不运行 frontier | 度量“让预算”本身的代价 |
| 固定配置 A | 同一 `V/P/K/ψ/MAP`，同 `W=nmb`/`variant`：基线 `early/prio` vs frontier `time/priority/lazy` | 构造器等价/速度/Time 差异 |
| 固定配置 B/C | 同一配置，B=去窗口+门控候选扫描；C=B 最优上做一步偏离+rollout | 门控/前瞻归因 |

ABBA：`A → B → B(--reverse) → A(--reverse)`；每例显式预算取 `auto_budget(n_ops)`；
同会话串行。`T_before`/`T_after` 来自候选进程自身 stderr 的
`[frontier] enabled=… before=… after=… stop=…`。

---

## 3. 固定配置：构造器等价与真实墙钟

### 3.1 等价性（同 `W=nmb`、同 `variant`、同一份 `V/P/K/ψ/MAP`）

| 对照 | 相同 | 更好 | 更差 | 说明 |
| --- | --- | --- | --- | --- |
| `frontier_lazy` vs 基线 `early` | **28/28** | 0 | 0 | 3 个 ≥164k op 例按 sched 自身上限跳过 early；Time 逐位相同 |
| `frontier_priority` vs 基线 `prio` | **31/31** | 0 | 0 | 逐位相同 |
| `frontier_time(zf0)` vs `early` | 8 | 16 | 4 | **不同派发规则**，不是等价；ex5 448<504、K=2V 多例更好，r16/r64_v8 等更差 |
| `frontier_time(zf1)` vs `zf0` | **31/31** | 0 | 0 | 零时长立即执行未改变任何 Time |
| `frontier_gated_time` vs `time(zf1)`（带窗口） | 30 | 0 | 1 | 门控在带窗口时也几乎不改变调度 |

所有构造结果 `invalid_schedules=0`；峰值/used 逐例记录在 JSON。

### 3.2 真实构造墙钟（无计数包装；单候选、同拓扑）

`frontier(time) / base_early` 的墙钟比：

| n_ops 区间 | 例数 | 中位 | 最小 | 最大 |
| --- | --- | --- | --- | --- |
| <2k | 10 | 3.56× | 0.59× | 4.33× |
| 2k–20k | 14 | 1.81× | 0.98× | 3.08× |
| 20k–100k | 4 | 0.87× | 0.18× | 2.10× |
| ≥100k | — | 基线 `early` 被自身 200k 上限禁用，无法同口径比 | — | — |

> 结论：事件内核的“工程优势”只在大规模出现（35,840 op 的 r256：0.25s vs 1.38s，
> 0.18×），小/中规模反而更慢（队列/前沿管理常数）。t2 微基准的 21.9s 是给基线堆操作
> 套计数包装器的结果，**只用于证明堆访问次数按 ~n² 增长，不作训练加速**。
> 计数明细：40,960 op 基线约 1,415 万次 heappush/pop、事件内核 7.5 万次；真实墙钟差异
> 远小于计数比。

---

## 4. B/C 固定配置：搜索、门控与一步前瞻

### 4.1 B 独立替换基线（同配置候选扫描 vs 基线端到端官方 Time）

| 集合 | 更好 | 更差 | 相同 | 基线合计 Time | B 合计 Time |
| --- | --- | --- | --- | --- | --- |
| samples7 | 0 | 4 | 2 | 16,824 | 17,812 |
| mini-even | 0 | 0 | 1 | 280 | 280 |
| fast12 | 7 | 2 | 3 | 228,955,850 | 228,615,937 |
| K=2V 6 例 | 3 | 3 | 0 | 107,060,752 | 108,709,649 |
| battery5 | 1 | 4 | 0 | 55,233,000,280,599,176 | 54,071,271,543,463,168 |
| **合计** | **11** | **13** | **6** | — | — |

注：battery 合计更好完全由 `b13-balanced-compute`（−2.9%）拉动；同集合 b03/b05/b06/b08
分别 +9.5%/+2.1%/+1.4%/+4.9%。**不能用合计掩盖逐例退化**。

### 4.2 门控是否绑定

31 例 `gating_binding = 0`：`cap_act` 远大于实际峰值（例如 r16 的 `cap_act=25578`，
实际峰值远低），`cap_comm=2` 也不是限制。**因此 B 相对 A 的差异不能归因于生命周期门控**。
受控合成例（`V=1,P=2,L=2,nmb=8,Mexp=20,M=25,U=Uact=1`，`cap_act=3`）：
基线整数窗口最好 298，门控 288（−3.4%，双判合法），这是“本次找到的”门控生效形状，
不是排他性定理。

### 4.3 C：一步偏离 + 贪心 rollout（不是全状态 beam）

C 在 B 最优解上对最多 6 个冲突点做“换同刻候选 / 同刻暂时等待”的一步偏离，再用事件内核
贪心 rollout，只接受更优完整合法解。31 例上相对 B：**3 好 / 0 差 / 25 平**（ex2 5240→4928、
ex3 6536→6108、ex6 1828→1704，均更接近但仍不及基线）；大用例 `n_ops>120k` 直接降级，
`20k<n_ops≤120k` 只做一次关键路径延迟派发分支。**无收益 ≠ 所有前瞻无用**。

---

## 5. 端到端同预算 ABBA（T_fullB / T_before / T_after）

> 待 ABBA 完成后填入；原始证据：`runs/frontier/experiments/t4-e2e/<label>/summary.json`
> 与逐例 `.stderr`；汇总脚本 `runs/frontier/experiments/t4/analyze_e2e.py`。

### 5.1 汇总（ABBA，每臂 2 趟；官方 grader Time，中位数）

| 集合 | fullB 合计 | 候选合计 | 好/差/平 | strict_pass | 备注 |
| --- | --- | --- | --- | --- | --- |
| fast12 | 228,955,850 | 228,530,587 | 6/1/5 | 4/4 趟 True | −0.186% |
| samples | 17,104 | 17,104 | 0/0/7 | 4/4 趟 True | mini N/A；mini-even 单列且持平 |
| K=2V 6 例 | 107,060,752 | 106,011,521 | 3/0/3 | 4/4 趟 True | −0.98%，镜像共卡 |
| battery5 | 55,233,000,280,599,176 | 同左 | 0/0/5 | 4/4 趟 True | frontier 5/5 `stop=deadline`、无命中 |

所有臂 16 个 run 的 `status` 全是 `OK`，`eligible`/`official_valid` 与 `strict_pass` 全通过；
没有输入资格 unknown、本地判分失败或双判 Time 不一致。

候选命中/停止（两趟合计，逐例去重）：

| 集合 | 有命中病例 | 无命中 | stop 分布 |
| --- | --- | --- | --- |
| fast12 | 7/12（r24、r32、r64_v2、r256、x03、x05、x13） | 5 | complete 12/12 |
| K=2V 6 例 | 3/6（r20、x01、x15） | 3 | complete 6/6 |
| samples | 0/7 | 7 | skipped-lb 3、complete 5（mini 不计） |
| battery5 | 0/5 | 5 | deadline 5/5（每个只跑到 run=1/planned=2） |

### 5.2 逐例归因（有收益/回归的病例；数值为官方 Time）

| 用例 | T_fullB | T_before | T_after | Δ(预算让出) | Δ(frontier) | 净 Δ | run/hits/stop |
| --- | --- | --- | --- | --- | --- | --- | --- |
| r32_p8_ramp | 17,096,182 | 17,096,182 | 16,637,188 | 0 | −458,994 | −2.69% | 10/1/complete |
| x05_lr_tight_p6 | 16,417,874 | 16,417,874 | 16,309,154 | 0 | −108,720 | −0.66% | 10/1/complete |
| x13_lr_twochunk_p8 | 14,937,492 | 14,937,492 | 14,913,208 | 0 | −24,284 | −0.16% | 10/1/complete |
| x03_lr_trap_p3 | 12,421,204 | 12,421,204 | 12,410,687 | 0 | −10,517 | −0.08% | 10/2/complete |
| r256_v4_c4 | 64,625,020 | 64,856,102 | 64,612,898 | +231,082 | −243,204 | −0.02% | 10/1/complete |
| r64_v2_c2 | 2,600,248 | 2,600,248 | 2,600,232 | 0 | −16 | −0.001% | 10/1/complete |
| r20_p2_flat (K=2V) | 31,321,175 | 31,321,175 | 30,820,592 | 0 | −500,583 | −1.60% | 10/2/complete |
| x01_lr_block_p2 (K=2V) | 2,922,720 | 2,922,720 | 2,812,400 | 0 | −110,320 | −3.78% | 10/2/complete |
| x15_lr_twochunk_p10 (K=2V) | 17,099,568 | 17,099,568 | 16,661,240 | 0 | −438,328 | −2.56% | 10/2/complete |
| r24_p4_block（ABBA 正向） | 51,491,190 | 53,132,030 | 52,569,830 | +1,640,840 | −562,200 | +1.08M | 10/1/complete |
| r24_p4_block（ABBA 反向） | 51,491,190 | 51,603,640 | 50,791,330 | +112,450 | −812,310 | −0.70M | 9/1/deadline |

`Δ(预算让出) = T_before − T_fullB`；`Δ(frontier) = T_after − T_before`；
`T_after − T_fullB` 才是净收益。**r24 是唯一出现正净 Δ 的病例**，见 §5.3。

### 5.3 r24 离群与 no-op 控制

- 候选 5 次独立运行：`52,569,830`（ABBA 正向）、`50,791,330`（反向）、`50,970,670` ×3
  （补充重复）→ 中位 `50,970,670`，相对 fullB `51,491,190` 为 **−1.01%**。
- no-op 控制（同样预留 0.9 s、不运行 frontier）：r24 ×3 = `51,491,190`（与 fullB 相同），
  r32 ×1 = `17,096,182`（与 fullB 相同）→ **预留预算本身没有系统性代价**。
- 结论：ABBA 正向的 `T_before=53,132,030` 是墙钟截断选到不同 (V,P,K,ψ) 的离群，不是
  预留的稳定成本；按 5 次重复看 r24 也是收益。但截断离群仍是**真实风险**（单次可能 +2%），
  t5 的 ABBA 需要每例重复 ≥3 次才能排除。

---

## 6. K=2V、battery 与边界

- **K=2V**：fast12 中 4 例为 K=2V（r16/r24/r32/x03/x05/x13 中的实际 K）；另取 6 例
  K=2V 官方用例（r20_p2_flat、r24_p3_flat、x01、x06、x10、x15）做固定配置对照，
  镜像共卡全部通过 `check_schedule`/`memory_usage`；B 独立替换 3 好/3 差。
- **battery5**：640k op 的 b05/b06 上基线 `early` 被自身上限禁用，事件内核仍可构造；
  Time 比基线端到端差（b05 +2.1%、b06 +1.4%），b13 更好（−2.9%）。
- **mini / mini-even**：mini 只作本地回归（官方 nmb=1 拒绝）；mini-even 双判合法且
  Time=280=lb，构造器等价性通过。
- **边界**：t2 的紧内存/死锁/零时长回归仍在 `test_frontier.py`；本轮未新增生产依赖或
  离线 oracle 依赖。

---

## 7. 冻结参数与启用建议

- 候选代码冻结在本文 commit；参数见 §1；`seed=20261020`；随机性只在 C 的固定顺序中，
  固定迭代上限下确定。
- **默认保持关闭**，除非 §5 的 ABBA 显示“收益可复现、无回归、合法/时限全过”；任一集合
  出现回归即保留实验入口与负面结论，不默认启用。
- 若未来启用：建议只对 `n_ops≤20k` 的配置启用预留；`>20k` 的候选扫描成本与收益需 t5
  再评估（当前大例只有 b13 一例收益，且 b13 同时是 640k 偏斜形状，不能外推）。

---

## 8. 复现命令

```bash
cd /home/rainy/hackathon/work-frontier-sgs
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1

# 固定配置消融（单集合）
python3 tools/frontier_ablate.py --baseline-dir runs/frontier/baseline/baseline-official50 \
    --set fast12 --out runs/frontier/experiments/t4/fixed-fast12.json
python3 tools/frontier_ablate.py --baseline-dir runs/frontier/baseline/baseline-battery13 \
    --set battery5 --max-ops-search 120000 \
    --out runs/frontier/experiments/t4/fixed-battery5.json

# 候选入口（显式启用）+ 单例
python3 tools/frontier_candidate.py <case.in> <out> --budget 7.6

# 端到端 ABBA（示例：fast12）
python3 tools/frontier_bench.py --label fast12-A --set fast12 \
    --solver /home/rainy/hackathon/work-frontier-baseline/src/solver/solve_all.py \
    --worktree /home/rainy/hackathon/work-frontier-baseline \
    --out runs/frontier/experiments/t4-e2e/fast12-A
python3 tools/frontier_bench.py --label fast12-B --set fast12 \
    --solver tools/frontier_candidate.py --worktree . \
    --out runs/frontier/experiments/t4-e2e/fast12-B
# 再跑 --reverse 两趟，最后
python3 runs/frontier/experiments/t4/analyze_e2e.py
```

---

## 9. 验证与合规

| 项 | 结果 |
| --- | --- |
| `make test` | 通过（judge 66 + solver 35，含 frontier 17 项；1 既有 skip） |
| `judge.core.acceptance` | 7/7 通过 |
| 固定配置消融合法性 | `invalid_schedules=0/31`；全部过 `check_schedule` + `memory_usage` |
| 官方 grader + 本地 judge | ABBA 记录逐例 `official`/`local`；`strict_pass` 见 §5 |
| 输入资格 | 只由官方 grader 判定；mini N/A、mini-even 可双判；unknown/local fail/time mismatch 不计通过 |
| 基线记录 | 未覆盖 `runs/frontier/baseline/**`；只读固定配置 |
| 其他 worktree | baseline 仍 detached `c558d9b`、git status 干净；未改 fill_boost/ILS/placement/psi |

---

## 10. 未解决/负面结论

- 生命周期门控在官方形状（fast12/K=2V/battery）上没有绑定，**没有可归因的 Time 收益**；
  只在受控紧内存合成例上体现机制价值。
- B 独立替换基线在 samples/K=2V/battery 上出现退化；C 只能部分追回小例差距。
- 事件内核只在 ≥20k op 附近体现构造速度优势；小例更慢。
- 零时长零等待没有 Time 收益（操作提前不等于 makespan 改善）。
- 下一步（t5）应只对“fast12 有收益且 ABBA 无回归”的候选做正式 50/13/留出集验收；
  否则保留实验入口与本文负面结论，默认不改。

---

## 11. 冻结记录

- 代码 commit：`83638d07edc983f98dae8878b763efb7dc4eae17`（t4 冻结；t5 审此版本）。
- 文档 commit：本文所在 commit（见 `git log -- docs/reports/frontier-experiments.md`）。
- 运行产物：`runs/frontier/experiments/t4/`（fixed-*.json、analyze_e2e.py、run_*.sh）
  与 `runs/frontier/experiments/t4-e2e/`（16 个 run 目录、summary.json、逐例 stderr）。
- 固定配置来源哈希：见 `runs/frontier/baseline/*/meta.json`（t3 冻结，未覆盖）。
