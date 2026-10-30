#pragma once
// Shared problem and result value types.
#include "../common.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../search/limits.hpp"
namespace solver {
using namespace std;
using i128 = __int128_t;
struct InputData {
    int N, S, L, E, k, mb;
    i128 M, Bi, Bo, Z, Zs, U, Ua, d, b, Fs, Fio, Fin, ax, bx;
    vector<i128> T;
    vector<vector<i128>> load;
};
struct Candidate {
    int P = 0, V = 0;
    i128 score = 0;
    vector<int> cuts;
    vector<vector<int>> map;
};
struct PartitionCandidate {
    Candidate best_v, max_v;
    i128 probe_time = search_limits::kInfiniteTime;
};
struct ScheduleResult {
    Candidate c;
    int G = 0, K = 0;
    i128 time = search_limits::kInfiniteTime;
    vector<int> cuts, group;
    vector<event_sched::Op> ops;
};

}  // namespace solver
