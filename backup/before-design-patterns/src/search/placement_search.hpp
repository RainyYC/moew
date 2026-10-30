#pragma once
#include "../model/problem.hpp"
namespace solver {
ScheduleResult run_alt_placement(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& v5_base, bool serial,
                                 const std::string& borrow);
}
