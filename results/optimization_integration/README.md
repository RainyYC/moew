# 当前搜索整合的验收记录

算法提交：`7ce6bc426515cf275adbf2ca9962e79939752196`。合入前标签 `20327` 指向 `c4d0fc33c5575a47bf7d03a581dc17dd92e6a0fe`。

本轮真实运行 50 例，官方 grader **50/50 通过，0 超时，平均 Time 20,247,910.26**，总 Time 1,012,395,513。原始证据为 [official-run-all.txt](full50/official-run-all.txt)，对齐明细为 [summary.tsv](full50/summary.tsv)，统计为 [validation.json](full50/validation.json)。

## 复现

```sh
make -j2 build
make submission submission-check
./scripts/test_search_modules.sh
make options-check strategy-check
python3 -u data/official/Problem/run_all.py \
  --cmd "python3 scripts/capture_solver_run.py build/solver results/optimization_integration/full50/raw" \
  --timeout 10
python3 scripts/summarize_integration_run.py
```

也可不保存逐例诊断，直接执行 `python3 data/official/Problem/run_all.py --cmd "./build/solver" --timeout 10`。两条命令都使用未修改的官方 runner 和 grader。截止式搜索会随运行环境产生分数波动，本目录只记录本轮完整批次，没有在多次运行中择优拼接。

包装器每例执行真实 C++ 求解器，保存 stdout/stderr 后原样转交给 runner，不回放任何保存的答案。其 9.75 秒子进程截止是独立的失败保护；官方外层限时仍为 10 秒。正式墙钟、CPU 含包装器，grader 耗时不计入。runner 平均墙钟 9.23112 秒、最大 9.262 秒；包装器单独计量的求解子进程平均墙钟 9.19792 秒、最大 9.22572 秒，见 [execution_details.json](execution_details.json)。

## 比较口径

| 记录 | 平均 Time | 相对当前批次的含义 |
|---|---:|---|
| 原在线记录 | 20,369,802.98 | 当前平均降低 121,892.72；13 改善、32 持平、5 退步 |
| 20327 离线集合 | 20,327,058.04 | 当前平均降低 79,147.78；12 改善、25 持平、13 退步 |
| 后续长时离线集合 | 20,224,564.90 | 当前平均仍高 23,345.36；10 改善、25 持平、15 退步 |
| 本轮在线实测 | **20,247,910.26** | 一次完整的 50 例实际求解 |

离线记录是实验中逐例保留的答案集合，不受本轮单例 10 秒条件限制。离线回放验收只证明那些答案合法，不测量构造答案的运行时间。正式源码不读取这些集合、文件名映射或保存的答案。原在线比较取自既有记录，未在本轮重跑，因此不是同机同时的成对性能实验。

[baseline_reference.json](baseline_reference.json) 说明标签与原始路径；两个 `offline_*.tsv` 保存离线分数和答案摘要供核对，其他字段沿用实验记录，生产算法不依赖这些字段。完整算法解释、逐点改善和全部退步点见[报告第 8、12、13 节](../../docs/reports/current-solver-report.md)。

## 构建与检查

[command.json](command.json) 保存编译器、编译参数、运行命令和二进制 SHA256；[SOURCE_SHA256SUMS](SOURCE_SHA256SUMS) 保存模块、提交件及构建文件摘要。生产文件为 24 个 `.cpp` 和 29 个 `.hpp`，测试源码不计入。

- `make -j2 build`、单文件导出/一致性和普通 `g++ -std=c++17 -O2` 编译通过。
- 选项解析与静态策略接口检查通过，相关日志在 [checks](checks/)。
- 搜索模块检查通过：$L=8$ 全切分穷举对照连续/折返 DP，组合缓存、镜像层数、实际切分、插值、缓存保护，以及排序/完整性/DAG/引擎/内存边界。
- 普通编译提交件的开发单例已通过官方 grader；正式 50 例使用多文件二进制，不拼接该单例分数。
- `run_all.py` 与 `grader.py` 的 SHA256 与合入前一致，见 `command.json`。

`checks` 中的单例和构建日志属于开发检查。最终提交件经过刷新后再次通过一致性与普通编译检查；正式成绩只取 `full50/official-run-all.txt`。正式批次的逐例原始答案、日志和本地二进制不上传 GitHub，可按以上命令重新生成。
