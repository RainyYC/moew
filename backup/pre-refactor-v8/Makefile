.PHONY: build smoke check official official-serial report help

.DEFAULT_GOAL := build

build:
	./scripts/build.sh

smoke: build
	./scripts/run_acceptance.sh smoke ac auto '^(x01_lr_block_p2|x18_vl_tight_small)$$' auto

check: smoke

official: official-serial

official-serial: build
	./scripts/run_acceptance.sh run_latest ac auto '' auto

report:
	@cat docs/reports/scale-v8.md

help:
	@printf '%s\n' \
	  'make (默认)       编译 build/solver' \
	  'make build        编译求解器' \
	  'make smoke        用官方 grader 验收 x01 与 x18' \
	  'make check        与 smoke 相同' \
	  'make official     串行验收官方 50 例' \
	  'make official-serial 串行验收官方 50 例' \
	  'make report       显示当前 v8 报告' \
	  'make help         显示命令帮助'
