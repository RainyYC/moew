#include "list_search.hpp"
// List-scheduler strategy and its local parameter sweeps.
#include "../scheduling/list_scheduler.hpp"
#include "layout_search.hpp"
#include "limits.hpp"
#include "../placement/expert_mapping.hpp"
#include "../io/numeric.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/list_scheduler.hpp"
#include "window_search.hpp"
namespace solver {
using namespace std;
ScheduleResult run_v7_list_search(const InputData& x, ScheduleResult best, bool serial,
                                  bool do_list, bool list_deep, bool list_deep_topos,
                                  bool diff_enabled, chrono::steady_clock::time_point main_start,
                                  const string& borrow) {
    if (!serial && do_list) {
        bool list_cutoff = false;
        const auto list_budget = list_deep
                                     ? chrono::milliseconds(search_limits::kListDeepDeadlineMs)
                                     : chrono::milliseconds(search_limits::kListNormalDeadlineMs);
        ScheduleResult anchor = best;
        auto dur = compute_durations(x, anchor.c);
        vector<int> ng(anchor.G);
        for (int g : anchor.group) {
            ng[g]++;
        }
        auto safe = [&](const vector<event_sched::Op>& ops, i128& tm) -> bool {
            int stride = x.L * operation::kCount, N = x.mb * stride;
            vector<i128> st(N, -1), en(N, -1);
            tm = 0;
            for (auto& o : ops) {
                int id = (o.mb * x.L + o.l) * operation::kCount + o.op;
                st[id] = o.start;
                en[id] = o.start + dur[o.l][o.op];
                tm = max(tm, en[id]);
            }
            for (int i = 0; i < N; i++) {
                if (st[i] < 0) {
                    return false;
                }
            }
            auto peak = [](vector<pair<i128, i128>>& a) {
                sort(a.begin(), a.end());
                multiset<i128> ends;
                int best = 0;
                for (size_t i = 0; i < a.size();) {
                    size_t j = i;
                    while (j < a.size() && a[j].first == a[i].first) {
                        j++;
                    }
                    while (!ends.empty() && *ends.begin() < a[i].first) {
                        ends.erase(ends.begin());
                    }
                    best = max(best, (int)ends.size() + (int)(j - i));
                    for (size_t k = i; k < j; k++) {
                        ends.insert(a[k].second);
                    }
                    i = j;
                }
                return best;
            };
            for (int g = 0; g < anchor.G; g++) {
                i128 mexp = (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs);
                vector<pair<i128, i128>> acts, comms;
                for (int l = 0; l < x.L; l++) {
                    if (anchor.group[l] == g) {
                        for (int m = 0; m < x.mb; m++) {
                            int b = (m * x.L + l) * operation::kCount;
                            acts.push_back({en[b + operation::index(operation::kCombineForward)],
                                            st[b + operation::index(operation::kSharedBackward)]});
                            for (int o : operation::kCommunicationOperations) {
                                if (dur[l][o] > 0) {
                                    comms.push_back({st[b + o], en[b + o]});
                                }
                            }
                        }
                    }
                }
                i128 used = mexp + x.U * peak(comms) + x.Ua * peak(acts);
                if (used > x.M) {
                    return false;
                }
            }
            return true;
        };
        i128 base_time = anchor.time, busy = 0;
        for (int g = 0; g < anchor.G; g++) {
            i128 csum = 0, msum = 0;
            for (int l = 0; l < x.L; l++) {
                if (anchor.group[l] == g) {
                    for (int o = 0; o < operation::kCount; o++) {
                        (list_sched::comm(o) ? msum : csum) += dur[l][o];
                    }
                }
            }
            busy = max(busy, max(csum, msum));
        }
        int best_w = 0, best_variant = -1, best_gap = 0;
        string best_mode = "incumbent";
        bool best_boost = false;
        long double best_boost_value = 0;
        int best_fs = 0, best_fm = 0, best_ratio = 0;
        bool best_ramp = false;
        i128 plain_time = search_limits::kInfiniteTime;
        int plain_w = x.mb;
        bool gap_improved = false, skip_sweep = false;
        auto run = [&](int W, int vi, bool early, int gap, int fs, int fm, int ratio10, bool ramp) {
            if (chrono::steady_clock::now() - main_start > list_budget) {
                list_cutoff = true;
                return;
            }
            vector<list_sched::Op> lo;
            i128 tm;
            if (!list_sched::schedule(x.mb, x.L, anchor.G, anchor.group, dur, ng, W, vi, early, gap,
                                      fs, fm, busy, ratio10, ramp, lo, tm)) {
                return;
            }
            if (tm >= best.time && (ratio10 > 0 || tm >= plain_time)) {
                return;
            }
            vector<event_sched::Op> ops;
            ops.reserve(lo.size());
            for (auto& o : lo) {
                ops.push_back({o.start, o.mb, o.l, o.op});
            }
            i128 checked;
            if (!safe(ops, checked)) {
                return;
            }
            if (ratio10 == 0 && checked < plain_time) {
                plain_time = checked;
                plain_w = W;
            }
            if (checked >= best.time) {
                return;
            }
            sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
            });
            best.time = checked;
            best.ops = move(ops);
            best_w = W;
            best_variant = vi;
            best_gap = gap;
            best_mode = early ? "early" : "prio";
            best_boost = ratio10 > 0;
            best_boost_value = (long double)busy * ratio10 / 10;
            best_fs = fs;
            best_fm = fm;
            best_ratio = ratio10;
            best_ramp = ramp;
        };
        i128 node_count = (i128)x.mb * x.L * operation::kCount;
        if (node_count >= 5000 && node_count <= 150000 &&
            chrono::steady_clock::now() - main_start <
                chrono::milliseconds(search_limits::kQuickGapFillLatestStartMs)) {
            vector<list_sched::Op> lo;
            i128 tm;
            if (list_sched::schedule(x.mb, x.L, anchor.G, anchor.group, dur, ng, x.mb, 0, false, 0,
                                     0, 0, 0, 0, false, lo, tm, nullptr, nullptr, true, true) &&
                tm < best.time) {
                vector<event_sched::Op> ops;
                ops.reserve(lo.size());
                for (auto& o : lo) {
                    ops.push_back({o.start, o.mb, o.l, o.op});
                }
                i128 checked;
                if (safe(ops, checked) && checked < best.time) {
                    sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
                    });
                    best.time = checked;
                    best.ops = move(ops);
                    best_w = x.mb;
                    best_variant = 0;
                    best_gap = 0;
                    best_mode = "gap-fill";
                    best_boost = false;
                    gap_improved = true;
                }
            }
        }
        if (diff_enabled && borrow == "ac") {
            bool release_cutoff = false;
            ScheduleResult released = scan_release1(
                x, best, main_start + chrono::milliseconds(search_limits::kListReleaseDeadlineMs),
                release_cutoff);
            if (released.time < best.time) {
                best = move(released);
            }
            list_cutoff = list_cutoff || release_cutoff;
        }
        set<int> all_w;
        if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
            for (int w = 1; w <= x.mb; w++) {
                all_w.insert(w);
            }
        } else {
            for (int num : {1, 2}) {
                int w = x.mb * num / 2;
                if (w > 0) {
                    all_w.insert(w);
                }
            }
            for (auto [num, den] : vector<pair<int, int>>{{2, 3},
                                                          {1, 1},
                                                          {1, 2},
                                                          {1, 3},
                                                          {1, 4},
                                                          {1, 5},
                                                          {1, 6},
                                                          {1, 8},
                                                          {1, 12},
                                                          {1, 16},
                                                          {1, 24},
                                                          {1, 32}}) {
                int w = x.mb * num / den;
                if (w > 0) {
                    all_w.insert(w);
                }
            }
            for (int w : {32, 24, 16, 12, 8, 6, 4, 3, 2, 1}) {
                if (w <= x.mb) {
                    all_w.insert(w);
                }
            }
        }
        i128 per_layer = (x.E / anchor.c.P) * x.Z + x.Zs;
        if (x.Ua > 0) {
            for (int g = 0; g < anchor.G; g++) {
                i128 mexp = (i128)ng[g] * per_layer, allowed = (x.M - mexp - x.U) / x.Ua;
                if (allowed > 0 && ng[g] > 0) {
                    all_w.insert(max(1, min(x.mb, (int)(allowed / ng[g]))));
                }
            }
        }
        skip_sweep = gap_improved && (i128)best.time * 100 <= busy * x.mb * 108;
        vector<int> preferred;
        auto add_w = [&](int w) {
            if (w >= 1 && w <= x.mb && all_w.count(w) &&
                find(preferred.begin(), preferred.end(), w) == preferred.end()) {
                preferred.push_back(w);
            }
        };
        for (int w : {x.mb, anchor.G, 2 * anchor.G, anchor.G - 1, anchor.G + 1, 2 * anchor.G - 1,
                      2 * anchor.G + 1}) {
            add_w(w);
        }
        for (auto [num, den] : vector<pair<int, int>>{{1, 1},
                                                      {2, 3},
                                                      {1, 2},
                                                      {1, 3},
                                                      {1, 4},
                                                      {1, 5},
                                                      {1, 6},
                                                      {1, 8},
                                                      {1, 12},
                                                      {1, 16},
                                                      {1, 24},
                                                      {1, 32}}) {
            add_w(x.mb * num / den);
        }
        for (int w : {32, 24, 16, 12, 8, 6, 4, 3, 2, 1}) {
            add_w(w);
        }
        for (int w : all_w) {
            add_w(w);
        }
        vector<int> wins = preferred;
        const int priority_variants[] = {4, 5, 0};
        if (!skip_sweep) {
            for (int vi : priority_variants) {
                for (int w : wins) {
                    for (int gap : {0, 1}) {
                        run(w, vi, true, gap, 0, 0, 0, false);
                    }
                }
            }
        }
        // Try the most useful alternative topologies and priority mode after every window has had
        // its early pass.
        if (!skip_sweep && (!list_deep || list_deep_topos)) {
            for (int vi : {1, 2, 3, 6, 7}) {
                for (int w : wins) {
                    run(w, vi, true, 0, 0, 0, 0, false);
                }
            }
        }
        if (!skip_sweep && (!list_deep || list_deep_topos)) {
            for (int vi = 0; vi < 8; vi++) {
                for (int w : wins) {
                    run(w, vi, false, 0, 0, 0, 0, false);
                }
            }
        }
        int chosen_w = plain_time < search_limits::kInfiniteTime
                           ? plain_w
                           : x.mb;  // best safe unboosted list schedule
        set<int> fss, fms = {x.mb, max(1, x.mb / 2), max(1, x.mb / 4)};
        for (int fs : {1, 2, max(1, x.mb / 4), max(1, x.mb / 2), anchor.G}) {
            fss.insert(min(fs, anchor.G));
        }
        vector<int> ratios = {5, 10, 20, 50, 100};
        if (!skip_sweep && !list_deep_topos &&
            (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit ||
             (long double)x.mb <= 1.2L * anchor.G ||
             (long double)base_time / max((long double)1, (long double)busy * x.mb) > 1.25L)) {
            vector<int> boost_ws;
            if (list_deep) {
                for (int w : preferred) {
                    if (find(boost_ws.begin(), boost_ws.end(), w) == boost_ws.end()) {
                        boost_ws.push_back(w);
                    }
                }
            } else {
                boost_ws.push_back(chosen_w);
            }
            for (int w : boost_ws) {
                for (int vi : {4, 5}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                run(w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r, true);
                            }
                        }
                    }
                }
            }
            if (!list_deep) {
                for (int vi : {4, 5}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                run(chosen_w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r,
                                    false);
                            }
                        }
                    }
                }
                for (int vi : {0, 1, 2, 3, 6, 7}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                for (bool ramp : {true, false}) {
                                    run(chosen_w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r,
                                        ramp);
                                }
                            }
                        }
                    }
                }
            }
        }
        cerr << "LIST_V7 anchor=" << to_decimal(base_time) << " plain="
             << (plain_time < search_limits::kInfiniteTime ? to_decimal(plain_time) : "none")
             << " plainW=" << plain_w << " best=" << to_decimal(best.time) << " W=" << best_w
             << " mode=" << best_mode << " variant=" << best_variant << " gap=" << best_gap
             << " boost=" << best_boost_value << " fs=" << best_fs << " fm=" << best_fm
             << " ratio10=" << best_ratio << " ramp=" << best_ramp << " cutoff=" << list_cutoff
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count()
             << " checked=closed-interval\n";
    }
    return best;
}

}  // namespace solver
