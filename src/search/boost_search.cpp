#include "boost_search.hpp"
// Forward-fill priority search.
#include "../io/numeric.hpp"
#include "../placement/expert_mapping.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
#include "layout_search.hpp"
namespace solver {
using namespace std;
ScheduleResult run_boost_borrow(const InputData& x, ScheduleResult best,
                                const ScheduleResult& v5_base, bool serial, const string& borrow) {
    if (!serial && (borrow == "boost" || borrow == "boost_grid" || borrow == "all")) {
        ScheduleResult trial = v5_base;
        auto dur = compute_durations(x, v5_base.c);
        vector<int> ng(v5_base.G);
        for (int g : v5_base.group) {
            ng[g]++;
        }
        i128 boost_best_time = search_limits::kInfiniteTime;
        int best_fg = 0, best_fm = 0, best_ratio = 0, best_buffer = 0;
        bool best_flat = false;
        for (int one = 0; one <= 1; one++) {
            vector<int> caps(v5_base.G), buf(v5_base.G);
            bool ok = true;
            for (int g = 0; g < v5_base.G; g++) {
                bool zero = true;
                for (int l = 0; l < x.L; l++) {
                    if (v5_base.group[l] == g &&
                        (dur[l][operation::index(operation::kDispatchForward)] ||
                         dur[l][operation::index(operation::kCombineForward)] ||
                         dur[l][operation::index(operation::kCombineBackward)] ||
                         dur[l][operation::index(operation::kDispatchBackward)])) {
                        zero = false;
                    }
                }
                int b = zero ? 0 : 1;
                if (!zero && !one) {
                    i128 two = x.M - ng[g] * ((x.E / v5_base.c.P) * x.Z + x.Zs) - 2 * x.U;
                    if (two >= 0 && two / x.Ua >= ng[g]) {
                        b = 2;
                    }
                }
                i128 avail =
                    x.M - ng[g] * ((x.E / v5_base.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
                if (avail < 0) {
                    ok = false;
                    break;
                }
                caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                buf[g] = b;
                if (caps[g] < ng[g]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) {
                continue;
            }
            vector<tuple<int, int, int, bool, bool>> cfg;
            if (borrow == "boost_grid") {
                set<int> fss = {1, 2, max(1, v5_base.G / 2), v5_base.G},
                         fms = {max(1, x.mb / 4), max(1, x.mb / 2), x.mb};
                vector<int> ratios = {0, 5, 10, 20, 50, 100};
                for (int fg : fss) {
                    for (int fm0 : fms) {
                        for (int ratio : ratios) {
                            cfg.emplace_back(fg, fm0, ratio, false, false);
                        }
                    }
                }
                cfg.emplace_back(min(2, v5_base.G), min(x.mb, max(1, x.mb / 2)), 20, true, false);
            } else {
                int fs = min(v5_base.G, max(1, v5_base.G / 2)), fm = min(x.mb, 16);
                cfg.emplace_back(v5_base.G, min(x.mb, max(2, v5_base.G)), 0, false, false);
                cfg.emplace_back(fs, fm, 10, false, false);
                cfg.emplace_back(fs, fm, 20, false, false);
                cfg.emplace_back(fs, fm, 50, false, false);
                cfg.emplace_back(min(2, v5_base.G), min(x.mb, 8), 20, true, false);
            }
            for (auto [fg, fm0, ratio, flat, unused] : cfg) {
                (void)unused;
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, v5_base.G, v5_base.group, dur, ng};
                scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                scheduling::EventConfig config;
                config.activation_capacity = &caps;
                config.communication_buffers = &buf;
                config.mode = 3;
                config.fill_groups = fg;
                config.fill_microbatches = fm0;
                config.reward_tenths = ratio;
                config.flat_reward = flat;
                scheduling::ScheduleOutput output{ops, tm};
                if (scheduler.run(config, output)) {
                    if (tm < boost_best_time) {
                        boost_best_time = tm;
                        best_fg = fg;
                        best_fm = fm0;
                        best_ratio = ratio;
                        best_flat = flat;
                        best_buffer = one;
                    }
                    if (tm < trial.time) {
                        trial.time = tm;
                        trial.ops.swap(ops);
                    }
                }
            }
        }
        if (borrow == "boost_grid" && boost_best_time < search_limits::kInfiniteTime) {
            cerr << "BORROW_B_GRID_BEST P=" << v5_base.c.P << " G=" << best_fg << " M=" << best_fm
                 << " ratio=" << best_ratio << " flat=" << best_flat << " buffer=" << best_buffer
                 << " Time=" << to_decimal(boost_best_time) << " base=" << to_decimal(v5_base.time)
                 << "\n";
        }
        if (trial.time < best.time) {
            best = move(trial);
        }
    }
    return best;
}

}  // namespace solver
