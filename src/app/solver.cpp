#include "solver.hpp"
// Top-level phase orchestration; global main stays in solver.cpp.
#include "../io/input.hpp"
#include "../io/options.hpp"
#include "../io/output.hpp"
#include "../search/boost_search.hpp"
#include "../search/candidate_search.hpp"
#include "../search/initial_search.hpp"
#include "../search/limits.hpp"
#include "../search/list_search.hpp"
#include "../search/placement_search.hpp"
#include "../search/polish_driver.hpp"
#include "../search/wave_search.hpp"
#include "../search/window_borrow.hpp"
namespace solver {
using namespace std;
bool Solver::solve(const InputData& x, const Options& options,
                   chrono::steady_clock::time_point main_start, ScheduleResult& result) const {
    const bool serial = options.mode == SearchMode::kSerial;
    const bool do_list = options.mode == SearchMode::kFull || options.mode == SearchMode::kList;
    const bool list_deep = false, list_deep_topos = false;
    const bool diff_enabled = do_list && !serial;
    const bool do_wave = options.mode == SearchMode::kFull;
    const string borrow = "ac";
    vector<PartitionCandidate> pcs = generate_candidates(x, options.force_p);
    if (pcs.empty()) {
        return false;
    }
    InitialResults initial = refine_initial_candidates(x, pcs, serial);
    ScheduleResult best = move(initial.best);
    ScheduleResult probe_base = move(initial.probe_base);
    ScheduleResult v5_base = move(initial.v5_base);
    best = run_window_borrow(x, move(best), probe_base, v5_base, serial, borrow);
    best = run_boost_borrow(x, move(best), v5_base, serial, borrow);
    best = run_alt_placement(x, move(best), v5_base, serial, borrow);
    best = run_v7_list_search(x, move(best), serial, do_list, list_deep, list_deep_topos,
                              diff_enabled, main_start, borrow);
    ScheduleResult v7_incumbent = best;
    run_scale_v8_search(x, pcs, v7_incumbent, best, serial, do_wave, main_start);
    polish_final_schedule(x, best, serial, do_wave, main_start, search_limits::kDefaultBudgetMs,
                          options.retime_mode, options.polish_pass_limit);
    result = move(best);
    return true;
}

int run(int argc, char** argv) {
    try {
        auto main_start = chrono::steady_clock::now();
        ios::sync_with_stdio(false);
        cin.tie(nullptr);
        Options options = parse_options(argc, argv);
        if (options.help) {
            cout << "Usage: solver [options] [input-file|-]\n"
                    "Options:\n"
                    "  --mode=full|list|event|serial  Search profile (default: full)\n"
                    "  --force-p=N                   Restrict P; 0 means unrestricted\n"
                    "  --retime-mode=auto|wide       Select retiming arithmetic\n"
                    "  --polish-pass-limit=N         Limit polish passes; 0 means unlimited\n"
                    "  --help, -h                    Show this help\n";
            return 0;
        }
        ifstream input_file;
        istream* input = &cin;
        if (!options.input_path.empty() && options.input_path != "-") {
            input_file.open(options.input_path);
            if (!input_file) {
                throw runtime_error("cannot open input file: " + options.input_path);
            }
            input = &input_file;
        }
        InputData x = read_input(*input);
        ScheduleResult result;
        if (!Solver{}.solve(x, options, main_start, result)) {
            cerr << "no feasible config\n";
            return 2;
        }
        write_output(x, result, options.mode == SearchMode::kSerial);
    } catch (const exception& e) {
        cerr << "input/options error: " << e.what() << "\n";
        return 2;
    }
    return 0;
}

}  // namespace solver
