#pragma once
#include "../common.hpp"
namespace solver {
enum class SearchMode { kFull, kList, kEvent, kSerial };

struct Options {
    int force_p = 0;
    SearchMode mode = SearchMode::kFull;
    int polish_pass_limit = 0;
    std::string retime_mode = "auto";
    std::string input_path;
    bool help = false;
};
Options parse_options(int argc, char** argv);
}  // namespace solver
