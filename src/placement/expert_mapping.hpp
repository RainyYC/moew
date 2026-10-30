#pragma once
#include "../model/problem.hpp"
namespace solver {
std::vector<std::vector<int>> build_expert_map(const InputData& x, int P, i128& cost);
std::vector<std::array<i128, operation::kCount>> compute_durations(const InputData& x,
                                                                   const Candidate& c);
}  // namespace solver
