#pragma once
#include "../model/problem.hpp"
namespace solver {
ScheduleResult evaluate_layouts(
    const InputData& x, const Candidate& c, bool rich, bool deep,
    std::chrono::steady_clock::time_point deadline = std::chrono::steady_clock::time_point::max());
}
