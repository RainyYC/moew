# `runs/` 数据目录

| 路径 | 内容 |
|---|---|
| `ledger.jsonl` | 账本：一行一次运行，**只追加**（`flock` + `fsync`），不改历史 |
| `ops/<run_id>/<case>.jsonl` | 逐步调度，每行一个 op（账本只存路径） |
| `out/<run_id>/<case>.out` | 该次运行提交/求解出的输出原文（可复核、可做编辑器预览） |

说明：

* 修正一个错误版本用**新 run**，不要编辑旧行；
* `ops` 全量可能 64 万条（`L=64, nmb=1000`），只能经 `GET /api/runs/<id>/cases/<case>/ops`
  的切片接口读（`since`/`until`/`group`/`mb`/`limit`/`cursor`）；
* `selftest` 用临时目录（`JUDGE_RUNS_DIR`）跑，不会污染这里的账本。
