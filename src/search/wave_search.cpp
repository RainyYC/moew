#include "wave_search.hpp"
// Scale-v8 wave strategy and validation.
#include "../io/numeric.hpp"
#include "../placement/expert_mapping.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/list_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
#include "candidate_search.hpp"
#include "layout_search.hpp"
#include "limits.hpp"
#include "list_search.hpp"
namespace solver {
using namespace std;
void run_scale_v8_search(const InputData& x, const vector<PartitionCandidate>& pcs,
                         const ScheduleResult& v7_incumbent, ScheduleResult& best, bool serial,
                         bool do_wave, chrono::steady_clock::time_point main_start,
                         chrono::steady_clock::time_point deadline) {
    const auto wave_deadline =
        min(main_start + chrono::milliseconds(search_limits::kWaveDeadlineMs), deadline);
    vector<ScheduleResult> scale_alt_seeds;
    if (!serial && do_wave && x.mb <= search_limits::kExtraLayoutMicrobatchLimit &&
        (i128)x.mb * x.L * operation::kCount <= search_limits::kExtraLayoutNodeLimit &&
        x.L > best.G &&
        chrono::steady_clock::now() - main_start <
            chrono::milliseconds(search_limits::kWaveWarmupMs) &&
        chrono::steady_clock::now() < wave_deadline) {
        const int incumbent_p = best.c.P;
        vector<int> order(pcs.size());
        iota(order.begin(), order.end(), 0);
        sort(order.begin(), order.end(),
             [&](int a, int b) { return pcs[a].probe_time < pcs[b].probe_time; });
        int used = 0;
        auto alt_deadline = wave_deadline;
        for (int pi : order) {
            const Candidate& c = pcs[pi].best_v.P ? pcs[pi].best_v : pcs[pi].max_v;
            if (!c.P || c.P == incumbent_p) {
                continue;
            }
            if (used >= 2 || chrono::steady_clock::now() +
                                     chrono::milliseconds(search_limits::kWaveExtensionReserveMs) >=
                                 alt_deadline) {
                break;
            }
            auto d_alt = compute_durations(x, c);
            int max_v = max(1, min({x.L, search_limits::kMaximumPartitionCount, x.N * x.S / c.P}));
            i128 max_c = 0, max_n = 0, total_c = 0, total_n = 0;
            for (int l = 0; l < x.L; l++) {
                i128 C = 0, N = 0;
                for (int o = 0; o < operation::kCount; o++) {
                    (list_sched::comm(o) ? N : C) += d_alt[l][o];
                }
                max_c = max(max_c, C);
                max_n = max(max_n, N);
                total_c += C;
                total_n += N;
            }
            i128 lb =
                max({(i128)x.mb * max_c, (i128)x.mb * max_n, ceil_div((i128)x.mb * total_c, max_v),
                     ceil_div((i128)x.mb * total_n, max_v)});
            if (lb >= best.time) {
                continue;
            }
            ++used;
            ScheduleResult alt = evaluate_layouts(x, c, true, true, alt_deadline);
            if (alt.ops.empty()) {
                continue;
            }
            scale_alt_seeds.push_back(alt);
            if (alt.time < best.time) {
                cerr << "SCALE_ALT_P oldP=" << best.c.P << " newP=" << alt.c.P
                     << " old=" << to_decimal(best.time) << " new=" << to_decimal(alt.time)
                     << " LB=" << to_decimal(lb) << "\n";
                best = alt;
            }
        }
    }
    if (!serial && do_wave) {
        vector<ScheduleResult> scale_seeds;
        scale_seeds.push_back(v7_incumbent);
        for (auto& alt : scale_alt_seeds) {
            scale_seeds.push_back(alt);
        }
        for (ScheduleResult anchor : scale_seeds) {
            if (chrono::steady_clock::now() >= wave_deadline) {
                break;
            }
            ScheduleResult saved_best = best;
            best = anchor;
            const auto wave_start = chrono::steady_clock::now();
            auto dur = compute_durations(x, anchor.c);
            vector<int> ng(anchor.G);
            for (int g : anchor.group) {
                ng[g]++;
            }
            auto safe_wave = [&](const vector<event_sched::Op>& ops, i128& tm) {
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
                                acts.push_back(
                                    {en[b + operation::index(operation::kCombineForward)],
                                     st[b + operation::index(operation::kSharedBackward)]});
                                for (int o : operation::kCommunicationOperations) {
                                    if (dur[l][o] > 0) {
                                        comms.push_back({st[b + o], en[b + o]});
                                    }
                                }
                            }
                        }
                    }
                    if (mexp + x.U * peak(comms) + x.Ua * peak(acts) > x.M) {
                        return false;
                    }
                }
                return true;
            };
            struct Trial {
                i128 tm;
                int mode, A, B, phase, pn, pd, W, head, desc, dw;
            };
            vector<Trial> top;
            Trial winner{anchor.time, 0, 0, 0, 0, 0, 0, x.mb, 0, 0, 0};
            auto run_wave = [&](int mode, int A, int B, int phase, int pn, int pd, int head,
                                bool desc, int dw, int W) {
                if (chrono::steady_clock::now() > wave_deadline) {
                    return;
                }
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
                scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
                scheduling::ListConfig config;
                config.window = W;
                config.rank_mode = mode;
                config.rank_a = A;
                config.rank_b = B;
                config.phase = phase;
                config.pitch_numerator = pn;
                config.pitch_denominator = pd;
                config.duration_head = head;
                config.microbatch_descending = desc;
                config.weight_gradient_order = dw;
                config.fill_gaps = true;
                scheduling::ScheduleOutput output{ops, tm};
                if (!scheduler.run(config, output)) {
                    return;
                }
                i128 checked;
                if (!safe_wave(ops, checked)) {
                    return;
                }
                if (W == x.mb) {
                    Trial t{checked, mode, A, B, phase, pn, pd, W, head, 0, dw};
                    top.push_back(t);
                    sort(top.begin(), top.end(), [](auto& a, auto& b) { return a.tm < b.tm; });
                    if (top.size() > 2) {
                        top.pop_back();
                    }
                }
                if (checked < best.time) {
                    winner = {checked, mode, A, B, phase, pn, pd, W, head, 0, dw};
                    sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
                    });
                    best.time = checked;
                    best.ops = move(ops);
                }
            };
            vector<int> pitches = {1, 2, 4};
            run_wave(1, 2, 1, 0, 1, 1, 0, false, 0, x.mb);
            for (int pn : pitches) {
                for (int head : {1, 2}) {
                    run_wave(2, 1, 1, 0, pn, 4, head, false, 0, x.mb);
                }
            }
            run_wave(2, 1, 1, 0, 2, 4, 2, false, 1, x.mb);
            run_wave(2, 1, 1, 0, 2, 4, 2, false, 2, x.mb);
            vector<int> ws = {anchor.G, 2 * anchor.G, max(1, x.mb / 2), x.mb};
            sort(ws.begin(), ws.end());
            ws.erase(unique(ws.begin(), ws.end()), ws.end());
            for (size_t i = 0; i < top.size() && i < 2; i++) {
                for (int w : ws) {
                    if (w != x.mb) {
                        auto t = top[i];
                        run_wave(t.mode, t.A, t.B, t.phase, t.pn, t.pd, t.head, t.desc, t.dw, w);
                    }
                }
            }
            cerr << "WAVE_V8 anchor=" << to_decimal(anchor.time)
                 << " best=" << to_decimal(best.time)
                 << " improvement=" << to_decimal(anchor.time - best.time)
                 << " mode=" << winner.mode << " A=" << winner.A << " B=" << winner.B
                 << " phase=" << winner.phase << " pitch=" << winner.pn << "/" << winner.pd
                 << " head="
                 << (winner.head == 1   ? "ES"
                     : winner.head == 2 ? "EF"
                                        : "layerMean")
                 << " dw=" << winner.dw << " W=" << winner.W << " top=" << top.size() << " elapsed="
                 << chrono::duration<double>(chrono::steady_clock::now() - wave_start).count()
                 << " total="
                 << chrono::duration<double>(chrono::steady_clock::now() - main_start).count()
                 << "\n";
            ScheduleResult wave_result = best;
            best = move(saved_best);
            if (wave_result.time < best.time) {
                best = move(wave_result);
            }
        }
    }
}

}  // namespace solver
