#include "solver.hpp"
// Top-level phase orchestration; global main stays in solver.cpp.
#include "../io/input.hpp"
#include "../io/numeric.hpp"
#include "../io/options.hpp"
#include "../io/output.hpp"
#include "../search/boost_search.hpp"
#include "../search/candidate_search.hpp"
#include "../search/initial_search.hpp"
#include "../search/limits.hpp"
#include "../search/layout_bound_search.hpp"
#include "../search/list_search.hpp"
#include "../search/placement_search.hpp"
#include "../search/polish_driver.hpp"
#include "../search/priority_search.hpp"
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
    const bool small_full_search =
        options.mode == SearchMode::kFull && !serial &&
        x.mb <= search_limits::kExtraLayoutMicrobatchLimit &&
        (i128)x.mb * x.L * operation::kCount <= search_limits::kExtraLayoutNodeLimit &&
        x.L > best.G;
    const auto infinite_deadline = chrono::steady_clock::time_point::max();
    const auto list_deadline =
        small_full_search
            ? main_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.list_deadline_ms)
            : infinite_deadline;
    best = run_v7_list_search(x, move(best), serial, do_list, list_deep, list_deep_topos,
                              diff_enabled, main_start, borrow, list_deadline);
    ScheduleResult v7_incumbent = best;
    const auto wave_deadline =
        small_full_search
            ? main_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.wave_deadline_ms)
            : infinite_deadline;
    run_scale_v8_search(x, pcs, v7_incumbent, best, serial, do_wave, main_start, wave_deadline);
    if (small_full_search) {
        const auto layout_start = chrono::steady_clock::now();
        const auto layout_deadline = min(
            layout_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.layout_budget_ms),
            main_start + chrono::milliseconds(
                             search_limits::kSmallFullSearchBudget.layout_deadline_cap_ms));
        const i128 layout_anchor = best.time;
        vector<ScheduleResult> layout_seeds;
        if (chrono::steady_clock::now() < layout_deadline) {
            layout_seeds = search_layout_bounds(x, pcs, best, layout_deadline);
        }
        cerr << "LAYOUT_BOUND_STAGE seeds=" << layout_seeds.size()
             << " anchor_Time=" << to_decimal(layout_anchor) << " Time=" << to_decimal(best.time)
             << " elapsed="
             << chrono::duration<double>(chrono::steady_clock::now() - layout_start).count()
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count() << "\n";

        vector<ScheduleResult> priority_seeds;
        priority_seeds.reserve(layout_seeds.size() + 1);
        priority_seeds.push_back(v7_incumbent);
        for (auto& seed : layout_seeds) {
            if (!seed.ops.empty()) {
                priority_seeds.push_back(move(seed));
            }
        }
        const auto priority_start = chrono::steady_clock::now();
        const auto priority_deadline = min(
            priority_start + chrono::milliseconds(
                                 search_limits::kSmallFullSearchBudget.priority_budget_ms),
            main_start + chrono::milliseconds(
                             search_limits::kSmallFullSearchBudget.priority_deadline_cap_ms));
        const i128 priority_anchor = best.time;
        if (chrono::steady_clock::now() < priority_deadline) {
            refine_priority_schedules(x, priority_seeds, best, priority_deadline);
        }
        cerr << "PRIORITY_STAGE seeds=" << priority_seeds.size()
             << " anchor_Time=" << to_decimal(priority_anchor) << " Time=" << to_decimal(best.time)
             << " elapsed="
             << chrono::duration<double>(chrono::steady_clock::now() - priority_start).count()
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count() << "\n";
    }
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
