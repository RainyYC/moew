#pragma once
#include <chrono>

#include "../io/options.hpp"
#include "../model/problem.hpp"
namespace solver {
int run(int argc, char** argv);

class Solver {
public:
    bool solve(const InputData& input, const Options& options,
               std::chrono::steady_clock::time_point main_start, ScheduleResult& result) const;
};
}  // namespace solver
