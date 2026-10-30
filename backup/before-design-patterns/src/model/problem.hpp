#pragma once
// Shared problem and result value types.
#include "../common.hpp"
#include "../search/limits.hpp"
#include "scheduled_operation.hpp"
namespace solver {
using i128 = __int128_t;
struct InputData {
    int N, S, L, E, k, mb;
    i128 M, Bi, Bo, Z, Zs, U, Ua, d, b, Fs, Fio, Fin, ax, bx;
    std::vector<i128> T;
    std::vector<std::vector<i128>> load;
};
struct Candidate {
    int P = 0, V = 0;
    i128 score = 0;
    std::vector<int> cuts;
    std::vector<std::vector<int>> map;
};
struct PartitionCandidate {
    Candidate best_v, max_v;
    i128 probe_time = search_limits::kInfiniteTime;
};
struct ScheduleResult {
    Candidate c;
    int G = 0, K = 0;
    i128 time = search_limits::kInfiniteTime;
    std::vector<int> cuts, group;
    std::vector<event_sched::Op> ops;
};

}  // namespace solver
