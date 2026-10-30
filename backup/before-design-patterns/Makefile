.PHONY: build build-multi submission submission-check smoke check official official-serial report help

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
	./scripts/run_acceptance.sh smoke ac auto '^(x01_lr_block_p2|x18_vl_tight_small)$$' auto

check: smoke

official: official-serial

official-serial: build
	./scripts/run_acceptance.sh run_latest ac auto '' auto

report:
	@cat docs/reports/current-solver-report.md

help:
	@printf '%s\n' \
	  'make (默认)       编译 build/solver' \
	  'make build        增量编译多翻译单元求解器' \
	  'make submission   导出单文件 submission/solver.cpp' \
	  'make submission-check 检查单文件导出是否最新' \
	  'make smoke        用官方 grader 验收 x01 与 x18' \
	  'make check        与 smoke 相同' \
	  'make official     串行验收官方 50 例' \
	  'make official-serial 串行验收官方 50 例' \
	  'make report       显示当前求解器完整报告' \
	  'make help         显示命令帮助'
