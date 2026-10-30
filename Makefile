# MoE 分块与重叠吞吐优化 —— 常用命令
#
# 代码在 src/ 下（judge / solver / ui），所以所有 python 调用都带 PYTHONPATH=src。
# 直接跑某个脚本：PYTHONPATH=src python3 src/solver/solve_all.py <case.in> [out]

PY := PYTHONPATH=src python3

.PHONY: help check test solver judge service lint official fast six report clean

help:
	@echo "make check     全部校验（判题 + 求解器 + 服务 + 独立复算 + UI）"
	@echo "make test      只跑单测（judge 66 + solver 9）"
	@echo "make six       六个官方样例，应得 560 / 4880 / 6072 / 3200 / 416 / 1696"
	@echo "make fast      官方 50 例的 12 例冒烟子集（并行，约 15 s）"
	@echo "make official  官方 50 例全量（并行，约 45 s；对外报成绩用 make official-serial）"
	@echo "make clean     清理 __pycache__ 与临时输出"

check: judge solver service lint
	$(PY) tools/independent_check.py

test:
	PYTHONPATH=src python3 -m unittest discover -s src/judge/tests -q
	$(PY) -m unittest discover -s src/solver/selftests -t src -q

judge:
	$(PY) -m judge.core.acceptance

solver:
	$(PY) src/solver/solve_all.py --check

service:
	$(PY) -m judge.service.selftest

lint:
	$(PY) src/ui/lint_viewer.py

six:
	@for c in ex1 ex2 ex3 ex4 ex5 ex6; do \
	  printf "%-4s " $$c; \
	  $(PY) src/solver/solve_all.py cases/$$c.in /tmp/$$c.out 2>&1 | tail -1 | grep -oE 'Time=[0-9]+'; \
	done

fast:
	$(PY) tools/run_official.py --subset fast

official:
	$(PY) tools/run_official.py

official-serial:
	cd data/official/Problem && python3 run_all.py --cmd "python3 $(CURDIR)/src/solver/solve_all.py"

report:
	@echo "解题报告：docs/reports/solution-report.md"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf /tmp/ex*.out
