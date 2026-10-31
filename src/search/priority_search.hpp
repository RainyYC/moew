#pragma once
#include "../model/problem.hpp"

namespace solver {
void refine_priority_schedules(const InputData& x, const std::vector<ScheduleResult>& seeds,
                               ScheduleResult& best,
                               std::chrono::steady_clock::time_point deadline);
}  // namespace solver
