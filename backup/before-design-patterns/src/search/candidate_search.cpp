#include "candidate_search.hpp"
// Partition generation and dynamic-programming initialization.
#include "../placement/expert_mapping.hpp"
#include "../io/numeric.hpp"
#include "limits.hpp"
namespace solver {
using namespace std;
vector<PartitionCandidate> generate_candidates(const InputData& x, int force_p) {
    int R = x.N * x.S;
    i128 H = x.d * x.b / x.k;
    vector<PartitionCandidate> pcs;
    for (int P = 1; P <= min(R, x.E); P++) {
        if ((force_p && P != force_p) || x.E % P || (x.S % P && P % x.S)) {
            continue;
        }
        i128 mapcost;
        auto mp = build_expert_map(x, P, mapcost);
        i128 q = (x.E / P) * x.Z + x.Zs;
        bool zero_comms = true;
        vector<i128> pref(x.L + 1);
        for (int l = 0; l < x.L; l++) {
            i128 X = ceil_div(x.T[l] * H, P), pin = min(P, x.S) - 1, pout = P - 1 - pin;
            i128 com = max(ceil_div(pin * X, x.Bi), ceil_div(pout * X, x.Bo)) * x.Fio,
                 g = ceil_div(x.T[l], P) * x.Fin, s = x.T[l] * x.Fs;
            if (com) {
                zero_comms = false;
            }
            pref[l + 1] = pref[l] + 4 * com + 2 * g + 2 * s +
                          2 * ceil_div(x.ax * com, search_limits::kMillion) +
                          ceil_div(x.ax * g, search_limits::kMillion) +
                          ceil_div(x.ax * x.bx * g, search_limits::kTrillion) +
                          ceil_div(x.ax * s, search_limits::kMillion) +
                          ceil_div(x.ax * x.bx * s, search_limits::kTrillion);
        }
        PartitionCandidate pc;
        i128 best_score = search_limits::kInfiniteTime;
        int vmax = min({x.L, search_limits::kMaximumPartitionCount, R / P});
        for (int V = 1; V <= vmax; V++) {
            i128 INF = search_limits::kInfiniteTime;
            vector<vector<i128>> dp(V + 1, vector<i128>(x.L + 1, INF));
            vector<vector<int>> par(V + 1, vector<int>(x.L + 1, -1));
            dp[0][0] = 0;
            for (int j = 1; j <= V; j++) {
                for (int i = j; i <= x.L - (V - j); i++) {
                    for (int h = j - 1; h < i; h++) {
                        if (dp[j - 1][h] < INF &&
                            (i - h) * (q + x.Ua) + (zero_comms ? 0 : x.U) <= x.M) {
                            i128 val = max(dp[j - 1][h], pref[i] - pref[h]);
                            if (val < dp[j][i]) {
                                dp[j][i] = val, par[j][i] = h;
                            }
                        }
                    }
                }
            }
            if (dp[V][x.L] >= INF) {
                continue;
            }
            Candidate c;
            c.P = P;
            c.V = V;
            c.score = dp[V][x.L] * search_limits::kMillion + mapcost;
            c.map = mp;
            c.cuts.resize(V + 1);
            c.cuts[V] = x.L;
            int at = x.L;
            bool ok = true;
            for (int j = V; j > 0; j--) {
                int h = par[j][at];
                if (h < 0) {
                    ok = false;
                    break;
                }
                c.cuts[j - 1] = h;
                at = h;
            }
            if (!ok) {
                continue;
            }
            if (c.score < best_score) {
                best_score = c.score;
                pc.best_v = c;
            }
            pc.max_v = c;
        }
        if (pc.max_v.P) {
            pcs.push_back(move(pc));
        }
    }
    return pcs;
}

}  // namespace solver
