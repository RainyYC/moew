#include "solver.hpp"
// Top-level phase orchestration; global main stays in solver.cpp.
#include "../io/input.hpp"
#include "../io/options.hpp"
#include "../io/output.hpp"
#include "../search/boost_search.hpp"
#include "../search/candidate_search.hpp"
#include "../search/initial_search.hpp"
#include "../search/list_search.hpp"
#include "../search/placement_search.hpp"
#include "../search/polish_driver.hpp"
#include "../search/wave_search.hpp"
#include "../search/window_borrow.hpp"
namespace solver {
using namespace std;
int run(int argc, char** argv) {
    try {
        auto main_start = chrono::steady_clock::now();
        ios::sync_with_stdio(false);
        cin.tie(nullptr);
        Options options = parse_options(argc, argv);
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
        int force_p = options.force_p;
        bool serial = options.serial, do_list = options.do_list, list_deep = options.list_deep,
             list_deep_topos = options.list_deep_topos, force_wave = options.force_wave;
        string borrow = options.borrow, diff = options.diff, scale = options.scale;
        bool diff_enabled = !serial && (diff == "on" || (diff == "auto" && borrow == "ac"));
        if (diff_enabled) {
            do_list = true;
        }
        if (diff == "off") {
            do_list = false;
        }
        bool do_wave = !serial && (force_wave || scale == "on" ||
                                   (scale == "auto" && borrow == "ac" && diff == "auto"));
        if (borrow == "none" || diff == "off" || scale == "off") {
            do_wave = false;
        }
        vector<PartitionCandidate> pcs = generate_candidates(x, force_p);
        if (pcs.empty()) {
            cerr << "no feasible config\n";
            return 2;
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
        polish_final_schedule(x, best, serial, do_wave, main_start, options.budget_ms,
                              options.retime_mode, options.polish_pass_limit);
        write_output(x, best, serial);
    } catch (const exception& e) {
        cerr << "input/options error: " << e.what() << "\n";
        return 2;
    }
    return 0;
}

}  // namespace solver
