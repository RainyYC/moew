"""只读分析：隐藏测试点风险面（用 battery 的逐例参数做参数化推算，不跑完整求解）。

题面 §6 的真实测试点**不限定** N/S/nmb/L 组合；battery 只是我们自己造的一组点。
本脚本回答：
  1. `nmb` 很小时，`(nmb+V−1)/nmb` 的填充红利能有多大（V=L 时）？
  2. `V=L` 的 Mexp 是 L×((E/P)Z+Zs)，而题面只保证 M ≥ min_(V,P) 的那个值 ——
     哪些 (E/P) 下必须退到 V<L（否则 Mexp 就超 M）？
  3. K=2V 时卡组持层数与 K=V 推进 V=L 的关系（题面 §4.6：Mexp 按卡组持有层数计）。

命令：PYTHONPATH=. python3 runs/score-strategy-20261030/probe_hidden_risk.py
"""
import json

out = {"fill_gain_vs_nmb": [], "min_resident": [], "k2v_note": ""}

# 1) V=L 时的填充红利：Time ≈ (nmb+L−1) 块 · seg（battery 实测已证实这个式子）
for L in (4, 8, 16, 32, 64):
    for nmb in (2, 4, 8, 16, 32, 64, 128, 1000):
        out["fill_gain_vs_nmb"].append({
            "L": L, "nmb": nmb, "V_L_pipeline_blocks": nmb + L - 1,
            "ideal_blocks": nmb + 0, "ratio": round((nmb + L - 1) / nmb, 4),
        })

# 2) 最小驻留量：题面 §6 "M 不小于 min_(V,P)[(L/V)(E/P)Z + (L/V)Zs]"，
#    V=L 时的 Mexp = L×((E/P)Z+Zs)，两者之比 = V* = argmin
for L in (4, 8, 16, 32, 64):
    for per_layer_exp in (2**15, 2**20, 2**25, 2**30):
        # 给定 L 与每层每卡专家参数 ((E/P)Z+Zs)，最优 V* 让 Mexp 恰为 L/V × per_layer
        # 题面只保证 M ≥ min over (V,P)，而 V 的最大值是 L（每卡组 1 层）
        out["min_resident"].append({
            "L": L, "bytes_per_layer_per_card": per_layer_exp,
            "Mexp_at_V_eq_L": L * per_layer_exp,
            "ratio_Mexp_VL_over_min_resident": 1.0,  # V=L 恰是 min（V 越大 Mexp 越小）
            "note": "Mexp 随 V 单调下降，V=L 时最小；因此 V=L 不会因为静态参数被内存顶掉——"
                    "顶掉的只会是 V 超过 L 或 V·P>R",
        })

out["k2v_note"] = (
    "K=2V 时一个卡组持两块（层数与 K=V 推进 V=L 时相当），但**块数变成 2 倍**："
    "流水线按块推进，Time ≈ (nmb + K − 1) × seg_block，K=V 只有 V 块。"
    "battery 的 b02–b08/b10 用 V=L 已经把所有卡用满（V·P=R），K=2V 需要 V≤L/2，"
    "直接翻倍块数；probe_mirror_split.json 的静态核算也给出 K=2V 比值恒为 1.000。"
)
print(json.dumps(out, ensure_ascii=False, indent=1))
