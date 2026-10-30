#pragma once
#include "../model/problem.hpp"
namespace solver {
ScheduleResult run_window_borrow(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& probe_base, const ScheduleResult& v5_base,
                                 bool serial, const std::string& borrow);
}
