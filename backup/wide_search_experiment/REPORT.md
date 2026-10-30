# v8 扩宽 P/V 搜索实验

## 结论

对官方 50 例启用 `--extra-p=4 --extra-v=3` 后，grader 全部通过。与纯重构基线逐例比较，Time 改善 0 例、持平 50 例、退步 0 例。当前证据不支持把这轮扩宽搜索并入正式 `src/solver.cpp`；正式源码保持不变。

## 覆盖与耗时

- 总墙钟最大值：9.009s（纯重构基线最大 9.008s）；所有运行都在 10s 超时内完成。
- 扩宽阶段额外墙钟：平均 0.580s，中位数 0.214s，最大 2.433s。
- 50 例共选中 192 个 P 搜索位置（每例最多 4 个；其余是该实例可行 P 不足），实际访问 189 个；99 个 P 被安全的全局资源下界剪枝，3 个 P 因共享 9s 截止未启动。
- 在进入 DP 的 P 上生成 871 个可行 V 候选；171 个候选实际进入 rich event 调度，其中 67 个进行了 deep 镜像/切点搜索，包含 20 次对初始 rich-only 候选升级到 deep 的重评。
- V 侧统计：650 个低于 top-3 范围，47 个 exact P/V/cuts 已由足够级别的初始 rich/deep 覆盖，3 个候选因共享截止未调度；DP 本身没有中途截止。Compact-wave helper 对 50 个 anchor 做了后续检查。

这些数值描述的是受限搜索覆盖，不代表每个选中 P 的所有可行 V 都做了 deep。`--extra-p=4` / `--extra-v=3` 指定排序后候选数量的上限，并非固定并行参数 P=4、V=3；资源下界和进程共享截止会进一步减少实际评估数。

## 受限案例

- `x17_vl_tight_block`：只生成 1 个可行 V，且它已被初始 rich/deep 覆盖；其他 2 个被 P 资源下界剪枝，因此新增候选评估数为 0。
- `x18_vl_tight_small`：同样只有 1 个可行 V 且已覆盖；4 个 P 中 3 个被资源下界剪枝，新增候选评估数为 0。
- `r24_p3_flat`：9.007s 完成；请求前 4 个 P，只访问到 2 个，1 个被下界剪枝、2 个受截止限制。8 个可行 V 中仅 1 个实际调度，另有 2 个受截止限制。
- `r24_p4_block`：9.009s 完成；前 4 个 P 中 3 个进入访问，1 个被下界剪枝、1 个受截止限制；17 个可行 V 中调度 4 个，另 1 个受截止限制。

## 复现

在仓库根目录编译实验副本并运行全套脚本：

```bash
g++ -std=c++17 -O2 -pipe backup/wide_search_experiment/solver.cpp -o backup/wide_search_experiment/solver
backup/wide_search_experiment/run_full50.sh
```

脚本对每例使用 10s timeout 和官方 `data/official/Problem/grader.py`；逐例结果见 [summary.tsv](results/final_full50/summary.tsv)。单例复现以真实的 `x10_lr_tight_p8.txt` 为例：

```bash
timeout 10s backup/wide_search_experiment/solver --extra-p=4 --extra-v=3 < data/official/Problem/cases/x10_lr_tight_p8.txt > /tmp/moe-wide-x10.out
python3 data/official/Problem/grader.py data/official/Problem/cases/x10_lr_tight_p8.txt /tmp/moe-wide-x10.out
```

## 固定工件

- 源码 SHA256：`fef14bda8d9e4fc42433c75d9c8f7148bffc3a12137abe980c9ee4acd4e1e881`
- 二进制 SHA256：`f3caa838b5bb4492323fb4e194cf9641d6caa8b2c4f1f883f9d38dae78cd0913`
- 最终 50 例汇总 SHA256：`3a67ba9fcbff5d3b0af41d41f6df267a63035d3cc0a7c93bbbb7e5c212fe9776`

早期 pilot 记录单独保留在 `results/targeted.tsv`、`results/pilot_before_deep_fix.tsv` 和 `results/remaining.tsv`，不计入本结论。正式 `src/solver.cpp` 未由本实验修改。
