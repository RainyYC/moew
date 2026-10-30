#pragma once
#include "../common.hpp"
#include "../search/limits.hpp"
namespace solver {
struct Options {
    int force_p = 0;
    bool serial = false, do_list = false, list_deep = false, list_deep_topos = false;
    bool force_wave = false;
    int budget_ms = search_limits::kDefaultBudgetMs;
    int polish_pass_limit = 0;
    std::string retime_mode = "auto";
    std::string borrow = "ac", diff = "auto", scale = "auto";
    std::string input_path;
};
Options parse_options(int argc, char** argv);
}  // namespace solver
