#pragma once
#include "../model/problem.hpp"
namespace solver {
ScheduleResult run_v7_list_search(const InputData& x, ScheduleResult best, bool serial,
                                  bool do_list, bool list_deep, bool list_deep_topos,
                                  bool diff_enabled,
                                  std::chrono::steady_clock::time_point main_start,
                                  const std::string& borrow);
}
