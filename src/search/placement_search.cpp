#include "placement_search.hpp"
// Alternative expert placement search and rescheduling.
#include "../io/numeric.hpp"
#include "../placement/expert_mapping.hpp"
#include "../placement/grouped_placement.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
#include "layout_search.hpp"
#include "limits.hpp"
namespace solver {
using namespace std;
ScheduleResult run_alt_placement(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& v5_base, bool serial, const string& borrow) {
    if (!serial && (borrow == "placement" || borrow == "ac" || borrow == "all")) {
        Candidate alt = v5_base.c;
        const int P = alt.P, per = x.E / P;
        bool changed = false;
        int improved_layers = 0;
        map<vector<i128>, grouped_placement::Plan> cache;
        for (int l = 0; l < x.L; l++) {
            vector<i128> slots = x.load[l], key = slots;
            sort(key.begin(), key.end());
            vector<i128> base_load(P);
            for (int e = 0; e < x.E; e++) {
                base_load[alt.map[l][e]] += slots[e];
            }
            i128 cur = *max_element(base_load.begin(), base_load.end()),
                 total = accumulate(slots.begin(), slots.end(), (i128)0),
                 heavy = *max_element(slots.begin(), slots.end());
            i128 lower = max(ceil_div(total, P), heavy);
            if (cur <= lower) {
                continue;
            }
            grouped_placement::Plan plan;
            bool found = false;
            auto it = cache.find(key);
            if (it != cache.end()) {
                plan = it->second;
                found = true;
            } else {
                i128 lo = lower, hi = cur - 1;
                grouped_placement::Plan best_plan;
                for (int z = 0; z < search_limits::kPlacementPeakSearchSteps && lo <= hi; z++) {
                    i128 mid = lo + (hi - lo) / 2;
                    grouped_placement::Plan trial;
                    if (grouped_placement::find_at_peak(slots, P, per, mid, trial,
                                                        search_limits::kPlacementSearchBudget)) {
                        best_plan = move(trial);
                        hi = mid - 1;
                    } else {
                        lo = mid + 1;
                    }
                }
                if (best_plan.peak) {
                    plan = move(best_plan);
                    cache.emplace(key, plan);
                    found = true;
                }
            }
            if (!found) {
                continue;
            }
            vector<int> row;
            if (!grouped_placement::materialize(slots, plan, row)) {
                continue;
            }
            vector<i128> new_load(P);
            for (int e = 0; e < x.E; e++) {
                new_load[row[e]] += slots[e];
            }
            i128 nm = *max_element(new_load.begin(), new_load.end());
            if (nm < cur) {
                alt.map[l] = move(row);
                changed = true;
                ++improved_layers;
            }
        }
        if (changed) {
            ScheduleResult trial = v5_base;
            trial.c = alt;
            auto dur = compute_durations(x, alt);
            vector<int> ng(trial.G);
            for (int g : trial.group) {
                ng[g]++;
            }
            for (int one = 0; one <= 1; one++) {
                vector<int> caps(trial.G), buf(trial.G);
                bool ok = true;
                for (int g = 0; g < trial.G; g++) {
                    bool zero = true;
                    for (int l = 0; l < x.L; l++) {
                        if (trial.group[l] == g &&
                            (dur[l][operation::index(operation::kDispatchForward)] ||
                             dur[l][operation::index(operation::kCombineForward)] ||
                             dur[l][operation::index(operation::kCombineBackward)] ||
                             dur[l][operation::index(operation::kDispatchBackward)])) {
                            zero = false;
                        }
                    }
                    int b = zero ? 0 : 1;
                    if (!zero && !one) {
                        i128 two = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - 2 * x.U;
                        if (two >= 0 && two / x.Ua >= ng[g]) {
                            b = 2;
                        }
                    }
                    i128 avail = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
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
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, trial.G, trial.group, dur, ng};
                scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                scheduling::EventConfig config;
                config.activation_capacity = &caps;
                config.communication_buffers = &buf;
                scheduling::ScheduleOutput output{ops, tm};
                if (scheduler.run(config, output) && tm < trial.time) {
                    trial.time = tm;
                    trial.ops.swap(ops);
                }
            }
            if (borrow == "all" || borrow == "ac") {
                vector<int> wins;
                if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
                    for (int w = 1; w <= x.mb; w++) {
                        wins.push_back(w);
                    }
                } else {
                    wins = {1,          2, 30,      31,          32,
                            64,         0, trial.G, 2 * trial.G, max(1, trial.G - 1),
                            trial.G + 1};
                }
                sort(wins.begin(), wins.end());
                wins.erase(unique(wins.begin(), wins.end()), wins.end());
                for (int one = 0; one <= 1; one++) {
                    vector<int> caps(trial.G), buf(trial.G);
                    bool ok = true;
                    for (int g = 0; g < trial.G; g++) {
                        bool zero = true;
                        for (int l = 0; l < x.L; l++) {
                            if (trial.group[l] == g &&
                                (dur[l][operation::index(operation::kDispatchForward)] ||
                                 dur[l][operation::index(operation::kCombineForward)] ||
                                 dur[l][operation::index(operation::kCombineBackward)] ||
                                 dur[l][operation::index(operation::kDispatchBackward)])) {
                                zero = false;
                            }
                        }
                        int b = zero ? 0 : 1;
                        if (!zero && !one) {
                            i128 two = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - 2 * x.U;
                            if (two >= 0 && two / x.Ua >= ng[g]) {
                                b = 2;
                            }
                        }
                        i128 avail = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
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
                        vector<event_sched::Op> ops;
                        i128 tm;
                        scheduling::ProblemView problem{x.mb, x.L, trial.G, trial.group, dur, ng};
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
            if (trial.time < best.time) {
                best = move(trial);
                cerr << "BORROW_C P=" << P << " improved_MAP_layers=" << improved_layers
                     << " Time=" << to_decimal(best.time) << "\n";
            }
        }
    }
    return best;
}

}  // namespace solver
