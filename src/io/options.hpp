#pragma once
// Command-line options and validation.
#include "../common.hpp"
#include "../search/limits.hpp"
namespace solver {
using namespace std;
struct Options {
    int force_p = 0;
    bool serial = false, do_list = false, list_deep = false, list_deep_topos = false;
    bool force_wave = false;
    int budget_ms = search_limits::kDefaultBudgetMs;
    int polish_pass_limit = 0;
    string retime_mode = "auto";
    string borrow = "ac", diff = "auto", scale = "auto";
    string input_path;
};

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; i++) {
        string a = argv[i];
        if (a == "-") {
            if (!options.input_path.empty()) {
                throw runtime_error("multiple input paths");
            }
            options.input_path = a;
        } else if (!a.empty() && a[0] != '-') {
            if (!options.input_path.empty()) {
                throw runtime_error("multiple input paths");
            }
            options.input_path = a;
        } else if (a == "--baseline") {
            options.serial = true;
        } else if (a == "--list") {
            options.do_list = true;
        } else if (a == "--list-deep") {
            options.do_list = true;
            options.list_deep = true;
        } else if (a == "--list-deep-topos") {
            options.do_list = true;
            options.list_deep = true;
            options.list_deep_topos = true;
        } else if (a == "--wave") {
            options.force_wave = true;
        } else if (a.rfind("--scale=", 0) == 0) {
            options.scale = a.substr(8);
        } else if (a.rfind("--force-p=", 0) == 0) {
            options.force_p = stoi(a.substr(10));
        } else if (a.rfind("--borrow=", 0) == 0) {
            options.borrow = a.substr(9);
        } else if (a.rfind("--diff=", 0) == 0) {
            options.diff = a.substr(7);
        } else if (a.rfind("--budget-ms=", 0) == 0) {
            size_t used = 0;
            int value = stoi(a.substr(12), &used);
            if (used != a.size() - 12 || value < search_limits::kMinimumBudgetMs ||
                value > search_limits::kMaximumBudgetMs) {
                throw runtime_error("--budget-ms must be an integer from 9000 to 9500");
            }
            options.budget_ms = value;
        } else if (a.rfind("--retime-mode=", 0) == 0) {
            options.retime_mode = a.substr(14);
            if (options.retime_mode != "auto" && options.retime_mode != "wide") {
                throw runtime_error("--retime-mode must be auto or wide");
            }
        } else if (a.rfind("--polish-pass-limit=", 0) == 0) {
            size_t used = 0;
            int value = stoi(a.substr(20), &used);
            if (used != a.size() - 20 || value < 0) {
                throw runtime_error("--polish-pass-limit must be a nonnegative integer");
            }
            options.polish_pass_limit = value;
        }
    }
    return options;
}

}  // namespace solver
