#pragma once
#include "../common.hpp"
#include "../model/scheduled_operation.hpp"
namespace event_sched {
namespace limits {
inline constexpr int kReadyLookahead = 16;
inline constexpr int kEventCompletion = 0;
inline constexpr int kReservationReturn = 1;
}  // namespace limits
using i128 = __int128_t;
bool schedule(int mb, int L, int G, const std::vector<int>& layer_group,
              const std::vector<std::array<i128, operation::kCount>>& dur,
              const std::vector<int>& group_layers, const std::vector<int>& activation_capacity,
              const std::vector<int>& comm_buffers, int window, std::vector<Op>& out,
              i128& makespan, int mode = 0, int fill_groups = 0, int fill_mbs = 0,
              int reward_tenths = 0, bool flat_reward = false, int window_release = 0);
}  // namespace event_sched
