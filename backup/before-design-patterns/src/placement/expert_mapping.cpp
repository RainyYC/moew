#include "expert_mapping.hpp"
// Per-layer expert assignment and duration cost model.
#include "../io/numeric.hpp"
#include "../model/problem.hpp"
#include "../search/limits.hpp"
namespace solver {
using namespace std;
vector<vector<int>> build_expert_map(const InputData& x, int P, i128& cost) {
    vector<vector<int>> mp(x.L, vector<int>(x.E));
    cost = 0;
    for (int l = 0; l < x.L; l++) {
        vector<int> e(x.E);
        iota(e.begin(), e.end(), 0);
        sort(e.begin(), e.end(), [&](int a, int b) { return x.load[l][a] > x.load[l][b]; });
        vector<i128> loads(P);
        vector<int> cnt(P);
        for (int id : e) {
            int r = -1;
            for (int j = 0; j < P; j++) {
                if (cnt[j] < x.E / P && (r < 0 || loads[j] < loads[r])) {
                    r = j;
                }
            }
            mp[l][id] = r;
            ++cnt[r];
            loads[r] += x.load[l][id];
        }
        i128 total = 0, heavy = 0, sq = 0;
        for (auto v : x.load[l]) {
            total += v;
            heavy = max(heavy, v);
        }
        for (auto v : loads) {
            sq += v * v;
        }
        for (int it = 0; it < 6; it++) {
            i128 mx = *max_element(loads.begin(), loads.end());
            if (mx == max(heavy, ceil_div(total, P))) {
                break;
            }
            vector<int> order(P);
            iota(order.begin(), order.end(), 0);
            sort(order.begin(), order.end(), [&](int a, int b) { return loads[a] > loads[b]; });
            int be = -1, bf = -1;
            i128 bm = mx, bs = sq;
            for (int a = 0; a < x.E; a++) {
                for (int b = a + 1; b < x.E; b++) {
                    int ra = mp[l][a], rb = mp[l][b];
                    if (ra == rb) {
                        continue;
                    }
                    i128 na = loads[ra] - x.load[l][a] + x.load[l][b],
                         nb = loads[rb] - x.load[l][b] + x.load[l][a], outside = 0;
                    for (int r : order) {
                        if (r != ra && r != rb) {
                            outside = loads[r];
                            break;
                        }
                    }
                    i128 nm = max(outside, max(na, nb)),
                         ns =
                             sq - loads[ra] * loads[ra] - loads[rb] * loads[rb] + na * na + nb * nb;
                    if (nm < bm || (nm == bm && ns < bs)) {
                        bm = nm;
                        bs = ns;
                        be = a;
                        bf = b;
                    }
                }
            }
            if (be < 0) {
                break;
            }
            int ra = mp[l][be], rb = mp[l][bf];
            loads[ra] = loads[ra] - x.load[l][be] + x.load[l][bf];
            loads[rb] = loads[rb] - x.load[l][bf] + x.load[l][be];
            swap(mp[l][be], mp[l][bf]);
            sq = bs;
        }
        cost += *max_element(loads.begin(), loads.end());
    }
    return mp;
}
vector<array<i128, operation::kCount>> compute_durations(const InputData& x, const Candidate& c) {
    vector<array<i128, operation::kCount>> d(x.L);
    i128 H = x.d * x.b / x.k;
    for (int l = 0; l < x.L; l++) {
        vector<i128> load(c.P);
        for (int e = 0; e < x.E; e++) {
            load[c.map[l][e]] += x.load[l][e];
        }
        i128 m = *max_element(load.begin(), load.end()), X = ceil_div(x.T[l] * H, c.P),
             pin = min(c.P, x.S) - 1, pout = c.P - 1 - pin;
        i128 com = max(ceil_div(pin * X, x.Bi), ceil_div(pout * X, x.Bo)) * x.Fio, g = m * x.Fin,
             s = x.T[l] * x.Fs;
        d[l] = {};
        d[l][operation::kSharedForward] = s;
        d[l][operation::kDispatchForward] = com;
        d[l][operation::kExpertForward] = g;
        d[l][operation::kCombineForward] = com;
        d[l][operation::kSharedBackward] = ceil_div(x.ax * s, search_limits::kMillion);
        d[l][operation::kCombineBackward] = ceil_div(x.ax * com, search_limits::kMillion);
        d[l][operation::kExpertInputGradient] = ceil_div(x.ax * g, search_limits::kMillion);
        d[l][operation::kExpertWeightGradient] =
            ceil_div(x.ax * x.bx * g, search_limits::kTrillion);
        d[l][operation::kDispatchBackward] = ceil_div(x.ax * com, search_limits::kMillion);
        d[l][operation::kSharedWeightGradient] =
            ceil_div(x.ax * x.bx * s, search_limits::kTrillion);
    }
    return d;
}
}  // namespace solver
