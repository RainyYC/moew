#pragma once
#include "../common.hpp"
namespace grouped_placement {
using i128 = __int128_t;
namespace limits {
inline constexpr int kMaxWeightTypes = 4;
inline constexpr int kMaxRanks = 32;
inline constexpr int kMaxSlotsPerRank = 32;
inline constexpr std::uint64_t kDefaultNodeBudget = 250000;
}  // namespace limits
struct Plan {
    std::vector<i128> values;
    std::vector<std::vector<int>> rank_counts;
    i128 peak = 0;
};
bool find_at_peak(const std::vector<i128>& slots, int P, int per_rank, i128 target_peak, Plan& plan,
                  std::uint64_t node_budget = limits::kDefaultNodeBudget);
bool materialize(const std::vector<i128>& slots, const Plan& plan, std::vector<int>& row);
}  // namespace grouped_placement
