#pragma once
#include "../model/problem.hpp"

namespace solver {
bool is_feasible_schedule(const InputData& x, const ScheduleResult& schedule);
}  // namespace solver
