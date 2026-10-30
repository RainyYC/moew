#include "initial_search.hpp"
// Select initial candidates and preserve the baseline incumbents.
#include "layout_search.hpp"
#include "window_search.hpp"
namespace solver {
using namespace std;


InitialResults refine_initial_candidates(const InputData& x, vector<PartitionCandidate>& pcs,
                                         bool serial) {
    vector<ScheduleResult> probes;
    probes.reserve(pcs.size());
    for (auto& pc : pcs) {
        ScheduleResult r = evaluate_layouts(x, pc.max_v, false, false);
        pc.probe_time = r.time;
        probes.push_back(move(r));
    }
    int winner = 0;
    for (int i = 1; i < (int)probes.size(); i++) {
        if (probes[i].time < probes[winner].time) {
            winner = i;
        }
    }
    ScheduleResult best = move(probes[winner]);
    ScheduleResult probe_base = best;
    if (!serial) {
        vector<int> ord(pcs.size());
        iota(ord.begin(), ord.end(), 0);
        sort(ord.begin(), ord.end(),
             [&](int a, int b) { return pcs[a].probe_time < pcs[b].probe_time; });
        if (winner != ord[0]) {
            swap(ord[0], ord[find(ord.begin(), ord.end(), winner) - ord.begin()]);
        }
        for (int j = 0; j < min(2, (int)ord.size()); j++) {
            int id = ord[j];
            const Candidate& c = pcs[id].best_v.P ? pcs[id].best_v : pcs[id].max_v;
            ScheduleResult r = evaluate_layouts(x, c, true, j == 0);
            // Candidate replacement is strict on Time; equal values retain traversal order.
            if (r.time < best.time) {
                best = move(r);
            }
        }
    }
    // Freeze the complete v5 result, including its original P/V and rich schedule
    // competition. Every borrow experiment branches from this exact incumbent.
    ScheduleResult v5_base = best;
    return {move(best), move(probe_base), move(v5_base)};
}

}  // namespace solver
