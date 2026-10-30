import subprocess, sys, time, re, json
from pathlib import Path
ROOT = Path("/home/rainy/hackathon")
cases = sorted(p.stem for p in (ROOT/"data/official/Problem/cases").glob("*.txt"))
cap = float(sys.argv[1]) if len(sys.argv) > 1 else 9.0
hard = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
out = {}
for i, name in enumerate(cases, 1):
    t0 = time.monotonic()
    try:
        r = subprocess.run([sys.executable, "solver.py",
                            str(ROOT/f"data/official/Problem/cases/{name}.txt"),
                            f"/tmp/pyc_{name}.out", f"--time-cap={cap}"],
                           capture_output=True, text=True, timeout=hard)
        wall = time.monotonic() - t0
        m = re.search(r"Time=(\d+)", r.stderr or "")
        out[name] = {"time": int(m.group(1)) if m else None, "wall": round(wall,2)}
    except subprocess.TimeoutExpired:
        out[name] = {"time": None, "wall": hard}
    print(f"{i:2d}/50 {name:26s} {out[name]}", flush=True)
Path("/home/rainy/hackathon/py5/result_cap.json").write_text(json.dumps(out, indent=1))
tot=[v["time"] for v in out.values() if v["time"]]
print(f"均值 {sum(tot)/len(tot):,.0f}  合法 {len(tot)}/50")
