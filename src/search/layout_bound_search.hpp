#pragma once

#include "../model/problem.hpp"

namespace solver {
std::vector<ScheduleResult> search_layout_bounds(const InputData& x,
                                                 const std::vector<PartitionCandidate>& placements,
                                                 ScheduleResult& best,
                                                 std::chrono::steady_clock::time_point deadline);
}  // namespace solver
