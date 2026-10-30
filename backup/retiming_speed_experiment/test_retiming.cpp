#define main solver_entry
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
#include "solver.cpp"
#pragma GCC diagnostic pop
#undef main

#include <cassert>
#include <iostream>

namespace {
using local_engine_polish::i128;
using local_engine_polish::Stats;

struct Result {
    std::vector<event_sched::Op> ops;
    i128 time = 0;
    Stats stats;
};

Result polish_case(i128 duration, bool auto_mode) {
    constexpr int mb = 1, layers = 1, groups = 1;
    const std::vector<int> group = {0};
    std::vector<std::array<i128, 10>> durations(1);
    durations[0].fill(duration);

    std::vector<event_sched::Op> input;
    input.reserve(10);
    for (int op = 0; op < 10; op++) {
        input.push_back({(i128)op * duration, 0, 0, op});
    }

    Result result;
    result.time = (i128)10 * duration;
    const i128 memory_limit = (i128)1000000000 * 1000000000000000LL;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    const bool completed = local_engine_polish::polish(
        mb, layers, groups, group, durations, input, memory_limit, 1, 1, 1, result.ops, result.time,
        result.stats, deadline, 5000, 0, auto_mode);
    assert(completed);
    assert(result.ops.size() == 10);
    return result;
}

void assert_legal(const Result& result, i128 duration) {
    std::array<i128, 10> start{};
    std::array<bool, 10> seen{};
    for (const auto& op : result.ops) {
        assert(op.mb == 0 && op.l == 0 && op.op >= 0 && op.op < 10);
        assert(!seen[op.op]);
        seen[op.op] = true;
        start[op.op] = op.start;
        assert(op.start >= 0);
    }
    for (bool present : seen) {
        assert(present);
    }

    auto precedes = [&](int before, int after) {
        assert(start[after] >= start[before] + duration);
    };
    for (const auto& edge : std::array<std::pair<int, int>, 10>{
             {{1, 2}, {2, 3}, {0, 3}, {3, 4}, {3, 5}, {5, 6}, {5, 7}, {5, 9}, {6, 8}, {4, 8}}}) {
        precedes(edge.first, edge.second);
    }

    for (const std::vector<int>& resource :
         {std::vector<int>{0, 2, 4, 6, 7, 9}, std::vector<int>{1, 3, 5, 8}}) {
        std::vector<int> order = resource;
        std::sort(order.begin(), order.end(),
                  [&](int a, int b) { return std::tie(start[a], a) < std::tie(start[b], b); });
        for (size_t i = 1; i < order.size(); i++) {
            assert(start[order[i]] >= start[order[i - 1]] + duration);
        }
    }
    i128 observed_time = 0;
    for (i128 s : start) {
        observed_time = std::max(observed_time, s + duration);
    }
    assert(observed_time == result.time);
}

void compare(i128 duration) {
    const Result wide = polish_case(duration, false);
    const Result automatic = polish_case(duration, true);
    assert(wide.time == automatic.time);
    assert(wide.stats.evaluated == automatic.stats.evaluated);
    assert(wide.stats.accepted == automatic.stats.accepted);
    assert(wide.stats.tie_moves == automatic.stats.tie_moves);
    assert(wide.stats.strict_improve == automatic.stats.strict_improve);
    for (size_t i = 0; i < wide.ops.size(); i++) {
        assert(wide.ops[i].start == automatic.ops[i].start);
    }
    assert_legal(wide, duration);
    assert_legal(automatic, duration);

    std::cout << "duration=" << to_decimal(duration) << " Time=" << to_decimal(wide.time)
              << " evaluated=" << wide.stats.evaluated << " accepted=" << wide.stats.accepted
              << " tie=" << wide.stats.tie_moves << " strict=" << wide.stats.strict_improve << '\n';
    for (const auto& op : wide.ops) {
        std::cout << op.op << ':' << to_decimal(op.start) << ' ';
    }
    std::cout << '\n';
}
}  // namespace

int main() {
    compare(10);
    compare((i128)100000000000000000LL);
    compare((i128)10 * 1000000000000000000LL);
}
