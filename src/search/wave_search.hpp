#pragma once
#include "../model/problem.hpp"
namespace solver {
void run_scale_v8_search(const InputData& x, const std::vector<PartitionCandidate>& pcs,
                         const ScheduleResult& v7_incumbent, ScheduleResult& best, bool serial,
                         bool do_wave, std::chrono::steady_clock::time_point main_start,
                         std::chrono::steady_clock::time_point deadline =
                             std::chrono::steady_clock::time_point::max());
}
