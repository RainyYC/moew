#pragma once
// Release-one window sweep for the initial schedule.
#include "layout_search.hpp"
#include "limits.hpp"
namespace solver {
using namespace std;
ScheduleResult scan_release1(const InputData& x, const ScheduleResult& anchor,
                             chrono::steady_clock::time_point deadline, bool& cutoff) {
    ScheduleResult trial = anchor;
    auto dur = compute_durations(x, anchor.c);
    vector<int> ng(anchor.G);
    for (int g : anchor.group) {
        ++ng[g];
    }
    vector<int> wins;
    if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
        for (int w = 1; w <= x.mb; ++w) {
            wins.push_back(w);
        }
    } else {
        wins = {1,
                2,
                30,  // sampled window value retained for large batches

                31,
                32,
                search_limits::kWindowExhaustiveMicrobatchLimit,
                anchor.G,
                max(1, anchor.G - 1),
                anchor.G + 1,
                2 * anchor.G,
                max(1, 2 * anchor.G - 1),
                2 * anchor.G + 1,
                x.mb};
        for (int& w : wins) {
            w = min(w, x.mb);
        }
        sort(wins.begin(), wins.end());
        wins.erase(unique(wins.begin(), wins.end()), wins.end());
    }
    for (int one = 0; one <= 1 && !cutoff; ++one) {
        vector<int> caps(anchor.G), buf(anchor.G);
        bool ok = true;
        for (int g = 0; g < anchor.G; ++g) {
            bool zero = true;
            for (int l = 0; l < x.L; ++l) {
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
                i128 two = x.M - (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - 2 * x.U;
                if (two >= 0 && two / x.Ua >= ng[g]) {
                    b = 2;
                }
            }
            i128 avail =
                x.M - (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
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
        for (int w : wins) {
            if (chrono::steady_clock::now() >= deadline) {
                cutoff = true;
                break;
            }
            vector<event_sched::Op> ops;
            i128 tm;
            if (event_sched::schedule(x.mb, x.L, anchor.G, anchor.group, dur, ng, caps, buf, w, ops,
                                      tm, 0, 0, 0, 0, false, 1) &&
                tm < trial.time) {
                trial.time = tm;
                trial.ops.swap(ops);
            }
        }
    }
    return trial;
}

}  // namespace solver
