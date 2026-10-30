"""只读数据核对：把 13 个 battery 用例的 **judge 原始判定**（生产 vs `git archive HEAD` 基线）
整理成一张表，并核对 README / 验证报告里的数字。

输入（只读）：
  runs/val-t1-battery-20261029-2308/judge/current-<case>.json   # 工作区生产代码
  runs/val-t1-battery-20261029-2308/judge/iso-<case>.json       # git archive HEAD 基线
  runs/battery-current/<case>.out                               # 生产方上传的权威输出
  runs/val-t1-battery-20261029-2308/current/<case>.out          # 验证时重跑的输出

输出：JSON（stdout），含每例的 Time/lb/比值/改善、内存三块峰值、以及
"上传产物 vs 重跑产物"的 sha256 一致性。

命令：
    python3 runs/score-strategy-20261030/verify_battery_data.py \
        > runs/score-strategy-20261030/verify_battery_data.json
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(".")
VAL = ROOT / "runs/val-t1-battery-20261029-2308"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(kind: str, case: str) -> dict | None:
    path = VAL / "judge" / f"{kind}-{case}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data


def main():
    cases = sorted(p.stem.replace(".in", "") for p in (ROOT / "bigcases/battery").glob("*.in"))
    rows = []
    for case in cases:
        cur = load("current", case)
        base = load("iso", case)
        upload = sha256(ROOT / "runs/battery-current" / f"{case}.out")
        rerun = sha256(VAL / "current" / f"{case}.out")
        base_out = sha256(VAL / "iso-head-out" / f"{case}.out")
        groups = cur.get("groups") if cur else []
        peak_used = max((g["mexp"] + g["movl"] + g["mact"] for g in groups), default=None)
        rows.append({
            "case": case,
            "current": {
                "ok": cur.get("ok"), "time": cur.get("time"), "lb": cur.get("lb"),
                "V": cur.get("grid", {}).get("V"), "P": cur.get("grid", {}).get("P"),
                "K": cur.get("K"), "errors": cur.get("n_errors"),
                "time_over_lb": (cur.get("time") / cur.get("lb")) if cur and cur.get("lb") else None,
                "peak_mem_used": peak_used,
                "mem_limit": groups[0]["limit"] if groups else None,
                "peak_mem_ratio": (peak_used / groups[0]["limit"]) if groups and peak_used else None,
            },
            "baseline_head": {
                "ok": base.get("ok"), "time": base.get("time"), "lb": base.get("lb"),
                "V": base.get("grid", {}).get("V"), "P": base.get("grid", {}).get("P"),
            } if base else None,
            "improvement_vs_head": (
                (base["time"] - cur["time"]) / base["time"] if base and cur and cur.get("time") else None
            ),
            "sha256": {"upload": upload, "rerun": rerun, "baseline_out": base_out,
                       "upload_eq_rerun": upload == rerun},
        })
    json.dump(rows, __import__("sys").stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
