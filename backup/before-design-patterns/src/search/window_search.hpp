#pragma once
#include "../model/problem.hpp"
namespace solver {
ScheduleResult scan_release1(const InputData& x, const ScheduleResult& anchor,
                             std::chrono::steady_clock::time_point deadline, bool& cutoff);
}
