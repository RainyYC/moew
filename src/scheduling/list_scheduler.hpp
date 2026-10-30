#pragma once
#include "../common.hpp"
namespace list_sched {
namespace limits {
inline constexpr int kVariantCount = 8;
}
using i128 = __int128_t;
struct Op {
    i128 start;
    int mb, l, op;
};
using Dur = std::vector<std::array<i128, operation::kCount>>;
inline bool comm(int o) {
    return o == operation::kDispatchForward || o == operation::kCombineForward ||
           o == operation::kCombineBackward || o == operation::kDispatchBackward;
}
bool schedule(int mb, int L, int G, const std::vector<int>& grp, const Dur& d,
              const std::vector<int>& ng, int W, int vi, bool early, int gap, int fs, int fm,
              i128 busy, int ratio10, bool ramp, std::vector<Op>& out, i128& tm,
              std::vector<i128>* starts = nullptr, std::vector<i128>* ends = nullptr,
              bool wave_rank = false, bool fill_gaps = false, int rank_mode = 0, int A = 1,
              int B = 1, int phase = 0, int pitch_num = 1, int pitch_den = 1, int duration_head = 0,
              bool mb_desc = false, int dw_order = 0);
}  // namespace list_sched
