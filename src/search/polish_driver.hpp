#pragma once
#include "../model/problem.hpp"
namespace solver {
void polish_final_schedule(const InputData& x, ScheduleResult& best, bool serial, bool do_wave,
                           std::chrono::steady_clock::time_point main_start, int budget_ms,
                           const std::string& retime_mode, int polish_pass_limit);
}
