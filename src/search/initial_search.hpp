#pragma once
#include "../model/problem.hpp"
namespace solver {
struct InitialResults {
    ScheduleResult best;
    ScheduleResult probe_base;
    ScheduleResult v5_base;
};
InitialResults refine_initial_candidates(const InputData& x, std::vector<PartitionCandidate>& pcs,
                                         bool serial);
}  // namespace solver
