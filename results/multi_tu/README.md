# 多翻译单元构建验收

源码提交：`99a74de`。本次把维护工程改成真正的多文件编译：21 个 `.cpp` 分别编译成对象文件，再链接为 `build/solver`；25 个 `.hpp` 提供接口、值类型、常量、模板和必要的小型 inline 函数。候选顺序、整数运算、DAG、内存语义和搜索预算保持不变。单文件仅作为可选裁判导出件。

## 构建与接口检查

`src/sources.mk` 是构建和导出共用的源文件清单。`make -j2 build` 使用 C++17、`-O2 -pipe -Wall -Wextra -flto`，各 `.cpp` 经 `-c -MMD -MP` 生成 `build/obj/` 下的对象和依赖文件，随后链接。`scripts/build.sh` 调用同一 Make 构建入口。验证时仅覆盖 `TARGET=build/solver_multi_candidate`，沿用默认对象目录。

全部 25 个公共头文件已通过独立语法编译检查；多文件构建和导出件编译无警告。[增量构建 dry-run](incremental-make.log) 通过 `make -n -W src/io/input.cpp` 模拟单个实现文件变动，仅计划重编 `input.o` 并重新链接，不修改源文件时间戳。[头文件依赖检查](incremental-header-make.log) 按依赖文件中的路径拼写模拟 `input.hpp` 变动，仅计划重编实际依赖它的 `io/input.o` 和 `app/solver.o`。构建目录有 21 个对象文件及其 21 个依赖文件。

`make submission` 按同一清单展开所有实现文件及本地头文件，生成 `submission/solver.cpp`。[导出新鲜度检查](submission-check.log)通过。该单文件另外使用普通 `g++ -std=c++17 -O2 -pipe -Wall -Wextra` 编译，未依赖 LTO。

| 构建形式 | 二进制 SHA-256 |
|---|---|
| 多文件联合构建 | `a6d22606cb93c2cdeefba5a7572c575ab04396d5c694210c0b8e2fd0da6cf8bc` |
| 无 LTO 的单文件导出构建 | `d0fca8b54c062b3e6008a2cbb3394e06570a6ada462e42407403703b97ab7b05` |
| 拆分前对照 | `09a283409f48c7c06bb8e9d7f3fc2ac62c7ce7cf3f69628cb083e5f1235475b8` |

## 固定工作量和导出等价性

使用 [validate_multi_tu.py](../../scripts/validate_multi_tu.py) 对六例各执行两轮旧/新配对，第二轮交换先后顺序；每次 `--polish-pass-limit=24`，保持 stdin 管道打开，以用例文件名传参。每次输出均经官方 grader 检查，CPU 只统计求解器进程，不包含 grader。求解器、编译和浏览器渲染不并行运行。

24 次运行全部合法，12 组配对 stdout 字节及非墙钟 `LOCAL_ENGINE` 字段完全相同（保留目标 `Time` 和 `anchor_Time`）。六例为 `r128_v4_c4a`、`r16_p4_trap`、`x01_lr_block_p2`、`x10_lr_tight_p8`、`x12_lr_close_p10`、`x20_vl_flat_control`。完整记录见 [fixed_work/validation.json](fixed_work/validation.json)、[runs.json](fixed_work/runs.json)。

第一组每版本 12 次运行：对照平均 CPU 3.427204 秒，多文件版本 3.474177 秒，汇总增加 **1.3706%**。主要差异是 `r128_v4_c4a` 第一次新构建运行 4.710 秒，第二次为 4.273 秒。对此例增加两轮反向配对，四次输出仍相同，对照 CPU 总计 8.338599 秒，新构建 8.227918 秒，变化 **−1.3273%**。这些样本未显示稳定的单向性能回退，但不构成运行时间完全不变的保证；首轮记录全部保留，未删除偏慢样本。

无 LTO 单文件导出件另运行六例，全部通过 grader，stdout 和非墙钟搜索计数均与对应多文件构建记录一致。补充四次配对和六次导出验证见 [recheck/validation.json](recheck/validation.json)、[runs.json](recheck/runs.json)。

## 默认预算完整 50 例

本批次通过 [compare_solver_search.py](../../scripts/compare_solver_search.py) 串行运行官方 50 例，每例限时 10 秒，再调用官方 grader。参数、编译配置、源提交与二进制身份见 [command.json](full50/command.json)。

完整批次已完成，原始汇总在 [summary.tsv](full50/summary.tsv)，统计在 [validation.json](full50/validation.json)。

| 指标 | 结果 |
|---|---:|
| 官方 grader 合法通过 | 50/50 |
| 超时或失败 | 0 |
| 平均 Time | 20,365,419.20 |
| 相对上一冻结批次 | 3 改善、47 持平、0 退步 |
| 平均墙钟 | 9.222104 秒 |
| 最大墙钟 | 9.233171 秒（r64_v8_c8f） |

三个变化点分别为 `r24_p3_flat` 22,104,110 → 22,031,278，`x09_lr_skew_p6` 17,164,896 → 17,147,936，`x12_lr_close_p10` 27,959,850 → 27,942,558。默认搜索按绝对墙钟截止，迭代数和 Time 会随运行波动；本轮没有改变搜索算法，也不把这些单批次收益解读为稳定的算法提升。全量结果原样保留，不以补测较好的结果替换任何一行。

## 归档与复核

拆分前的源码、导出件、构建和文档快照位于 [backup/before-multi-tu](../../backup/before-multi-tu/)。上一批次 `results/module_refactor/full50/` 的校验清单仅把历史路径转向内容相同的快照；原始成绩没有改写。

本轮最终 `full50/SOURCE_SHA256SUMS` 校验提交内的源码、文档和验收汇总；`full50/SHA256SUMS` 另外记录本地构建及运行产物。二进制和逐次答案、日志依 `.gitignore` 留在本地。算法运行流程没有改变，本轮未启动长时间暴力优化实验。
