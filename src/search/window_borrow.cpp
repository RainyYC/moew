#include "window_borrow.hpp"
// Window-limit borrowing from frozen initial incumbents.
#include "../placement/expert_mapping.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
#include "layout_search.hpp"
#include "limits.hpp"
namespace solver {
using namespace std;
ScheduleResult run_window_borrow(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& probe_base, const ScheduleResult& v5_base,
                                 bool serial, const string& borrow) {
    if (!serial && (borrow == "windows" || borrow == "ac" || borrow == "all")) {
        auto scan_windows = [&](const ScheduleResult& anchor) {
            ScheduleResult trial = anchor;
            auto dur = compute_durations(x, anchor.c);
            vector<int> ng(anchor.G);
            for (int g : anchor.group) {
                ng[g]++;
            }
            vector<int> wins;
            if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
                for (int w = 1; w <= x.mb; w++) {
                    wins.push_back(w);
                }
            } else {
                wins = {1,
                        2,
                        30,  // sampled window value retained for large batches

                        31,
                        32,
                        search_limits::kWindowExhaustiveMicrobatchLimit,
                        0,
                        anchor.G,
                        2 * anchor.G,
                        max(1, anchor.G - 1),
                        anchor.G + 1,
                        max(1, 2 * anchor.G - 1),
                        2 * anchor.G + 1};
            }
            sort(wins.begin(), wins.end());
            wins.erase(unique(wins.begin(), wins.end()), wins.end());
            for (int one = 0; one <= 1; one++) {
                vector<int> caps(anchor.G), buf(anchor.G);
                bool ok = true;
                for (int g = 0; g < anchor.G; g++) {
                    bool zero = true;
                    for (int l = 0; l < x.L; l++) {
                        if (anchor.group[l] == g &&
                            (dur[l][operation::index(operation::kDispatchForward)] ||
                             dur[l][operation::index(operation::kCombineForward)] ||
                             dur[l][operation::index(operation::kCombineBackward)] ||
                             dur[l][operation::index(operation::kDispatchBackward)])) {
                            zero = false;
                        }
                    }
                    int b = zero ? 0 : 1;
                    if (!zero && !one) {
                        i128 two = x.M - ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - 2 * x.U;
                        if (two >= 0 && two / x.Ua >= ng[g]) {
                            b = 2;
                        }
                    }
                    i128 avail =
                        x.M - ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
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
                if (ok) {
                    for (int w : wins) {
                        vector<event_sched::Op> ops;
                        i128 tm;
                        scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
                        scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                        scheduling::EventConfig config;
                        config.activation_capacity = &caps;
                        config.communication_buffers = &buf;
                        config.window = w;
                        scheduling::ScheduleOutput output{ops, tm};
                        if (scheduler.run(config, output) && tm < trial.time) {
                            trial.time = tm;
                            trial.ops.swap(ops);
                        }
                    }
                }
            }
            return trial;
        };
        ScheduleResult a = scan_windows(probe_base), b = scan_windows(v5_base);
        ScheduleResult trial = (a.time <= b.time ? move(a) : move(b));
        if (trial.time < best.time) {
            best = move(trial);
        }
    }
    return best;
}

}  // namespace solver
