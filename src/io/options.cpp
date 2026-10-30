#include "options.hpp"

#include <charconv>

#include "../common.hpp"

namespace solver {
namespace {
int parse_nonnegative(const std::string& value, const std::string& option_name) {
    int parsed = 0;
    const char* begin = value.data();
    const char* end = begin + value.size();
    auto result = std::from_chars(begin, end, parsed);
    if (value.empty() || result.ec != std::errc() || result.ptr != end || parsed < 0) {
        throw std::runtime_error(option_name + " must be a nonnegative integer");
    }
    return parsed;
}
}  // namespace

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            options.help = true;
            return options;
        }
        if (arg == "-") {
            if (!options.input_path.empty()) {
                throw std::runtime_error("multiple input paths");
            }
            options.input_path = arg;
        } else if (arg.rfind("--mode=", 0) == 0) {
            std::string value = arg.substr(7);
            if (value == "full") {
                options.mode = SearchMode::kFull;
            } else if (value == "list") {
                options.mode = SearchMode::kList;
            } else if (value == "event") {
                options.mode = SearchMode::kEvent;
            } else if (value == "serial") {
                options.mode = SearchMode::kSerial;
            } else {
                throw std::runtime_error("--mode must be full, list, event, or serial");
            }
        } else if (arg.rfind("--force-p=", 0) == 0) {
            options.force_p = parse_nonnegative(arg.substr(10), "--force-p");
        } else if (arg.rfind("--retime-mode=", 0) == 0) {
            options.retime_mode = arg.substr(14);
            if (options.retime_mode != "auto" && options.retime_mode != "wide") {
                throw std::runtime_error("--retime-mode must be auto or wide");
            }
        } else if (arg.rfind("--polish-pass-limit=", 0) == 0) {
            options.polish_pass_limit = parse_nonnegative(arg.substr(20), "--polish-pass-limit");
        } else if (!arg.empty() && arg[0] != '-') {
            if (!options.input_path.empty()) {
                throw std::runtime_error("multiple input paths");
            }
            options.input_path = arg;
        } else {
            throw std::runtime_error("unknown option: " + arg + " (use --help)");
        }
    }
    return options;
}

}  // namespace solver
