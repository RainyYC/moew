.PHONY: build build-multi submission submission-check smoke options-check strategy-check check official official-serial report help

.DEFAULT_GOAL := build

include src/sources.mk
CXX ?= g++
CPPFLAGS ?= -Isrc
CXXFLAGS ?= -std=c++17 -O2 -pipe -Wall -Wextra -flto
LDFLAGS ?= -flto
TARGET ?= build/solver
BUILD_DIR ?= build/obj
OBJECTS := $(patsubst src/%.cpp,$(BUILD_DIR)/%.o,$(SOLVER_SOURCES))
DEPS := $(OBJECTS:.o=.d)

build: build-multi

build-multi: $(TARGET)

$(TARGET): $(OBJECTS) Makefile src/sources.mk
	$(CXX) $(CXXFLAGS) $(LDFLAGS) $(OBJECTS) -o $@

$(BUILD_DIR)/%.o: src/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c $< -o $@

-include $(DEPS)

submission:
	python3 scripts/amalgamate.py

submission-check:
	python3 scripts/amalgamate.py --check

smoke: build
	./scripts/run_acceptance.sh smoke full '^(x01_lr_block_p2|x18_vl_tight_small)$$'

options-check: build
	python3 scripts/test_options.py ./build/solver

strategy-check:
	@mkdir -p build
	g++ -std=c++17 -O2 -Wall -Wextra -Isrc scripts/test_strategy_api.cpp -o build/test_strategy_api
	./build/test_strategy_api

check: smoke options-check strategy-check

official: build
	python3 -u data/official/Problem/run_all.py --cmd "$(abspath $(TARGET))" --timeout 10

official-serial: build
	python3 -u data/official/Problem/run_all.py --cmd "$(abspath $(TARGET))" --timeout 10

report:
	@cat docs/reports/current-solver-report.md

help:
	@printf '%s\n' \
	  'make (默认)       编译 build/solver' \
	  'make build        增量编译多翻译单元求解器' \
	  'make submission   导出单文件 submission/solver.cpp' \
	  'make submission-check 检查单文件导出是否最新' \
	  'make smoke        用官方 grader 验收 x01 与 x18' \
	  'make options-check 验证命令行参数' \
	  'make strategy-check 编译运行策略注入示例' \
	  'make check        运行 smoke、CLI 和策略接口三类检查' \
	  'make official     使用官方 run_all.py 串行验收' \
	  'make official-serial 与 official 相同，直接运行官方脚本' \
	  'make report       显示当前求解器完整报告' \
	  'make help         显示命令帮助'
