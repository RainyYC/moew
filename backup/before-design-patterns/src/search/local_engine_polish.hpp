#pragma once
#include "../common.hpp"
#include "../model/scheduled_operation.hpp"
namespace local_engine_polish {
using i128 = __int128_t;
struct Stats {
    long long evaluated = 0, accepted = 0, strict_improve = 0, tie_moves = 0;
    int memory_fast_groups = 0;
    int rounds = 0;
    bool exhausted = true;
};
bool polish(int mb, int L, int G, const std::vector<int>& group,
            const std::vector<std::array<i128, operation::kCount>>& dur,
            const std::vector<event_sched::Op>& input, i128 memory, i128 U, i128 Ua,
            i128 resident_per_layer, std::vector<event_sched::Op>& output, i128& best_time,
            Stats& stats, std::chrono::steady_clock::time_point deadline,
            long long eval_limit = 12000, int pass = 0, bool retime_auto = true);
}  // namespace local_engine_polish
