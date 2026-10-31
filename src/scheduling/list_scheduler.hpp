#pragma once
#include "../common.hpp"
#include "../model/scheduled_operation.hpp"
namespace list_sched {
namespace limits {
inline constexpr int kVariantCount = 8;
}
using i128 = __int128_t;
using Op = solver::ScheduledOperation;
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
              bool mb_desc = false, int dw_order = 0, std::uint64_t random_seed = 0,
              int random_jitter_span = 1, int random_wave_stride = 1,
              const std::vector<i128>* microbatch_offset_ticks = nullptr,
              int microbatch_offset_denominator = 1);
}  // namespace list_sched
