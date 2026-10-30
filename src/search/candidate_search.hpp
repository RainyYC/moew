#pragma once
#include "../model/problem.hpp"
namespace solver {
std::vector<PartitionCandidate> generate_candidates(const InputData& x, int force_p);
}
