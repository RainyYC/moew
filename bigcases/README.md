# bigcases/ —— 大规模测试输入与实测基线

> 由 `python3 tools/gen_big.py --out bigcases` 生成。**不是题面官方用例**，只用于压测：
> 解析、校验、模拟、调度、ops 切片、账本体积。
>
> 题面范围（§6）：`N≤32, S≤16, R≤512, E≤512, L≤64, k≤64, nmb≤103 且偶数, T≤1e9, d≤2^16`。
> 因此**题面范围内单次运行最多约 `L·nmb·10 = 64×102×10 = 65 280` 条 op**；
> `stress-ops` 故意用 `nmb=1000` 超出范围，只用于验证切片接口在 64 万条下的表现。

## 输入

| 文件 | 规模 | 特点 | 题面范围内 |
| --- | --- | --- | --- |
| `big-wide.in` | R=512, L=64, E=512, nmb=102 | 全均衡负载，T=1e9 | ✅ |
| `big-skew.in` | 同上 | 逐层 Zipf 偏斜（每层方向不同） | ✅ |
| `big-mixed.in` | 同上 | 1/3 均衡 + 1/3 偏斜 + 1/3 极端（1/64 专家吃掉几乎全部） | ✅ |
| `big-tight.in` | 同上，`M=256MiB` | 内存受限，迫使 `P≥4`，AllToAll 真正参与 | ✅ |
| `big-small-nmb.in` | 同上，nmb=2 | "层多、mb 少"的形态 | ✅ |
| `stress-ops.in` | 同上，nmb=1000 | 64 万条 op，仅压测切片接口 | ❌ 超范围 |

## 实测基线（本机，4 核 / 16 GiB，Python 3.14）

| 用例 | ops | 求解器 | 判题 | 结果 | 备注 |
| --- | --- | --- | --- | --- | --- |
| big-wide | 65 280 | **8.07 s** | **0.32 s** | 合法 · Time 6.912e12 | 选 `V=64 P=1 D=8`，`x=0` 无通信 |
| big-skew | 65 280 | 8.17 s | 0.34 s | 合法 · Time 6.536e12 | 同上；**P=1 时偏斜无影响**（`m=Σa=T`） |
| big-mixed | 65 280 | 8.02 s | 0.31 s | 合法 · Time 6.912e12 | 与 big-wide 同值，印证上一条 |
| big-tight | 65 280 | 8.15 s | 0.53 s | 合法 · Time 2.435e15 | `M=256MiB` 迫使 `P=4`，`Bout=20000` 使通信主导 |
| big-small-nmb | 1 280 | 6.03 s | 0.11 s | 合法 · Time 2.112e12 | |
| stress-ops | **640 000** | 55.8 s（`--budget 60`） | **2.49 s** | 合法 | 超出题面范围 |

服务层（`judge serve`）：

| 场景 | 首次请求（建列式表） | 后续单页 | 视口切片 `since/until` |
| --- | --- | --- | --- |
| 65 280 ops | 0.20 s | 5.9 ms | 0.76 ms |
| 640 000 ops | 1.96 s | 6.7–7.0 ms | 1.2 ms |

## 两条从数据里看出来的结论

1. **`P=1` 在大 E 场景下是支配策略。** `P=1` 时 `x=0`，全部 AllToAll 消失，Time 退化为纯计算；此时 `m_ℓ = Σ_e a_{ℓ,e} = T_ℓ`，**负载偏斜完全不产生影响**（big-wide / big-skew / big-mixed 在 `P=1` 配置下同值即由此而来）。只有当内存逼迫 `P≥2`（如 `big-tight`）时，通信与偏斜才重新成为主要矛盾。
2. **求解器在最大规模上只剩约 1.9 s 余量**（8.1 s vs 10 s 上限）。单机空闲时安全；若与其它重负载并发，有超时风险。缓解办法：对 `n_ops` 大的用例降低 `nmb` 候选、缩短退火试次数，或把预算从 8.5 s 降到 7 s。

## 复跑

```bash
python3 tools/gen_big.py --out bigcases
python3 solver/solve_all.py bigcases/big-wide.in bigcases/out/big-wide.out
python3 -m judge eval bigcases/big-wide.in bigcases/out/big-wide.out
```
