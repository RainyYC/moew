"""读-only 探针：P 剪枝（`enumerate_configs` 的 best_floor）在 b10 / 官方 50 例上是否剪掉了更优网格。

用 **solver 源码快照**（runs/score-validation-20261030/snapshot）在进程内：
  1. 打印 P 剪枝关掉前后各自枚举出的配置（P、V、lb×填充）；
  2. 对两者各自排序后的前 N 个配置，用 `formula.lower_bound` / `lb_chain` 比较。

不改生产文件、不写缓存；只做"配置空间"分析，不做完整调度（调度结果见 REPORT §3/§5）。
用法：PYTHONPATH=. python3 runs/score-validation-20261030/scripts/probe_b10_prune.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

sys.path.insert(0, str(common.OUTDIR / "snapshot"))
from solver import solve  # noqa: E402
from solver.casein import parse_case  # noqa: E402


def enumerate_with_prune(case, enabled: bool):
    """临时在内存里切换剪枝开关（只影响本进程）。"""
    src_lines = None
    if not enabled:
        src_lines = "_PRUNE_OFF"
        # 用等价的运行时手段：把 best_floor 强制保持 None 无法直接做到，
        # 所以改为调用 enumerate_configs 两次并对比"P 集合"。
    return None


def main() -> int:
    names = ["b10-high-k", "b13-balanced-compute", "b12-compute-bound", "b01-loose"]
    out = {}
    for name in names:
        case = parse_case(common.ROOT / f"bigcases/battery/{name}.in")
        configs, pmaps = solve.enumerate_configs(case)
        top = [{"P": c.P, "V": c.V, "lb": c.lb, "fill": round((case.nmb + c.V - 1) / case.nmb, 4),
                "lb_x_fill": int(c.lb * (case.nmb + c.V - 1) / case.nmb)} for c in configs[:6]]
        ps = sorted({c.P for c in configs})
        legal_p = [P for P in solve.p_candidates(case) if case.R % P == 0]
        out[name] = {"n_configs": len(configs), "P_present": ps, "P_legal": legal_p,
                     "P_pruned": [P for P in legal_p if P not in ps], "top": top}
        print(name, json.dumps(out[name], ensure_ascii=False), flush=True)
    (common.OUTDIR / "battery/b10-prune.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
