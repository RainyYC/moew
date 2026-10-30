#include "layout_search.hpp"
// Evaluate group layouts under the event scheduler.
#include "../placement/expert_mapping.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
namespace solver {
using namespace std;
ScheduleResult evaluate_layouts(const InputData& x, const Candidate& c, bool rich, bool deep,
                                chrono::steady_clock::time_point deadline) {
    ScheduleResult best;
    best.c = c;
    auto dur = compute_durations(x, c);
    vector<int> base_group(x.L);
    for (int g = 0; g < c.V; g++) {
        for (int l = c.cuts[g]; l < c.cuts[g + 1]; l++) {
            base_group[l] = g;
        }
    }
    auto test_layout = [&](const vector<int>& lg, const vector<int>& cuts, int K, int G) {
        if (chrono::steady_clock::now() >= deadline) {
            return;
        }
        vector<int> ng(G);
        for (int g : lg) {
            ng[g]++;
        }
        vector<int> windows = rich ? vector<int>{1, 2, G, 2 * G, 0} : vector<int>{0};
        sort(windows.begin(), windows.end());
        windows.erase(unique(windows.begin(), windows.end()), windows.end());
        for (int one = 0; one <= (rich ? 1 : 0); one++) {
            vector<int> caps(G), buf(G);
            bool ok = true;
            for (int g = 0; g < G; g++) {
                bool zero = true;
                for (int l = 0; l < x.L; l++) {
                    if (lg[l] == g && (dur[l][operation::index(operation::kDispatchForward)] ||
                                       dur[l][operation::index(operation::kCombineForward)] ||
                                       dur[l][operation::index(operation::kCombineBackward)] ||
                                       dur[l][operation::index(operation::kDispatchBackward)])) {
                        zero = false;
                    }
                }
                // If every communication duration is zero, the official checker omits buffers.
                int bbuf = zero ? 0 : 1;
                if (rich && !one && !zero) {
                    i128 two = x.M - ng[g] * ((x.E / c.P) * x.Z + x.Zs) - 2 * x.U;
                    if (two >= 0 && two / x.Ua >= ng[g]) {
                        bbuf = 2;
                    }
                }
                i128 avail = x.M - ng[g] * ((x.E / c.P) * x.Z + x.Zs) - (zero ? 0 : bbuf * x.U);
                if (avail < 0) {
                    ok = false;
                    break;
                }
                caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                buf[g] = bbuf;
                if (caps[g] < ng[g]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) {
                continue;
            }
            int mmax = rich ? 2 : 0;
            for (int mode = 0; mode <= mmax; mode++) {
                for (int w : windows) {
                    if (chrono::steady_clock::now() >= deadline) {
                        return;
                    }
                    vector<event_sched::Op> ops;
                    i128 tm;
                    scheduling::ProblemView problem{x.mb, x.L, G, lg, dur, ng};
                    scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                    scheduling::EventConfig config;
                    config.activation_capacity = &caps;
                    config.communication_buffers = &buf;
                    config.window = w;
                    config.mode = mode;
                    scheduling::ScheduleOutput output{ops, tm};
                    if (scheduler.run(config, output) && tm < best.time) {
                        best.time = tm;
                        best.G = G;
                        best.K = K;
                        best.cuts = cuts;
                        best.group = lg;
                        best.ops.swap(ops);
                    }
                }
            }
        }
    };
    test_layout(base_group, c.cuts, c.V, c.V);
    if (rich && deep) {
        int max_g = min(x.L / 2, x.N * x.S / c.P);
        set<int> gs;
        for (int g : {max_g, min(max_g, c.V), max(1, min(max_g, c.V / 2))}) {
            if (g >= 1 && g <= max_g) {
                gs.insert(g);
            }
        }
        for (int G : gs) {
            if (chrono::steady_clock::now() >= deadline) {
                break;
            }
            int K = 2 * G;
            vector<int> cuts(K + 1), group(x.L);
            for (int j = 0; j <= K; j++) {
                cuts[j] = x.L * j / K;
            }
            for (int j = 0; j < K; j++) {
                for (int l = cuts[j]; l < cuts[j + 1]; l++) {
                    group[l] = (j < G ? j : 2 * G - 1 - j);
                }
            }
            test_layout(group, cuts, K, G);
        }
        if (best.time < search_limits::kInfiniteTime) {
            vector<i128> lw(x.L);
            for (int l = 0; l < x.L; l++) {
                for (auto v : dur[l]) {
                    lw[l] += v;
                }
            }
            vector<int> order;
            for (int j = 1; j < best.K; j++) {
                if (best.cuts[j] > 0 && best.cuts[j] < x.L) {
                    order.push_back(j);
                }
            }
            sort(order.begin(), order.end(), [&](int a, int b) {
                return abs((long long)(lw[best.cuts[a] - 1] - lw[best.cuts[a]])) >
                       abs((long long)(lw[best.cuts[b] - 1] - lw[best.cuts[b]]));
            });
            vector<int> seed = best.cuts;
            int K = best.K, G = best.G;
            int tried = 0;
            for (int j : order) {
                if (chrono::steady_clock::now() >= deadline) {
                    break;
                }
                for (int delta : {-1, 1}) {
                    if (chrono::steady_clock::now() >= deadline) {
                        break;
                    }
                    auto cuts = seed;
                    cuts[j] += delta;
                    bool ok = true;
                    for (int z = 1; z < K; z++) {
                        if (cuts[z] <= cuts[z - 1] || cuts[z] >= cuts[z + 1]) {
                            ok = false;
                        }
                    }
                    if (!ok) {
                        continue;
                    }
                    vector<int> group(x.L);
                    for (int bl = 0; bl < K; bl++) {
                        int g = (K == G ? bl : (bl < G ? bl : 2 * G - 1 - bl));
                        for (int l = cuts[bl]; l < cuts[bl + 1]; l++) {
                            group[l] = g;
                        }
                    }
                    test_layout(group, cuts, K, G);
                }
                if (++tried >= 3) {
                    break;
                }
            }
        }
    }
    if (best.time >= search_limits::kInfiniteTime) {
        best.G = c.V;
        best.K = c.V;
        best.cuts = c.cuts;
        best.group = base_group;
        best.time = 0;
        for (int mb = 0; mb < x.mb; mb++) {
            for (int l = 0; l < x.L; l++) {
                for (auto d : dur[l]) {
                    best.time += d + 1;
                }
            }
        }
    }
    return best;
}

}  // namespace solver
