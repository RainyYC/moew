#pragma once
#include "../common.hpp"
#include "../core/operation_graph.hpp"
#include "../model/scheduled_operation.hpp"

// ===== local_engine_polish =====

namespace local_engine_polish {
namespace limits {
inline constexpr int kOuterDeadlineCheckMask = 31;
inline constexpr int kInnerDeadlineCheckMask = 255;
inline constexpr int kBlockLengthMin = 4;
inline constexpr int kBlockLengthMax = 7;
inline constexpr int kVariantCycle = 4;
inline constexpr int kDistanceRotationMultiplier = 7;
inline constexpr int kResourceRotationMultiplier = 13;
inline constexpr int kOperationRotationMultiplier = 37;
inline constexpr int kPermutationStartMultiplier = 997;
inline constexpr int kPermutationWindowStride = 37;
inline constexpr int kDistanceRotationSpan = 8;
inline constexpr int kVariantDistanceStep0 = 12;
inline constexpr int kVariantDistanceStep1 = 16;
inline constexpr int kVariantDistanceStep2 = 24;
inline constexpr int kVariantDistanceStep3 = 32;
}  // namespace limits
using i128 = __int128_t;
struct Stats {
    long long evaluated = 0, accepted = 0, strict_improve = 0, tie_moves = 0;
    int memory_fast_groups = 0;
    int rounds = 0;
    bool exhausted = true;
};
inline int engine(int o) {
    return (o == operation::kDispatchForward || o == operation::kCombineForward ||
            o == operation::kCombineBackward || o == operation::kDispatchBackward)
               ? operation::kCommunicationEngine
               : operation::kComputeEngine;
}
inline int id(int m, int l, int o, int L) {
    return operation_graph::node_id(m, l, o, L);
}

// Fixed-layout local search. Each positive-duration operation occupies exactly
// one (group, engine) sequence. DAG and resource constraints are retimed by a
// longest-path pass after each trial ordering.
inline bool polish(int mb, int L, int G, const std::vector<int>& group,
                   const std::vector<std::array<i128, operation::kCount>>& dur,
                   const std::vector<event_sched::Op>& input, i128 M, i128 U, i128 Ua,
                   i128 resident_per_layer, std::vector<event_sched::Op>& output, i128& best_time,
                   Stats& stats, std::chrono::steady_clock::time_point deadline,
                   long long max_evaluations = 12000, int variant = 0, bool retime_auto = true) {
    if (std::chrono::steady_clock::now() >= deadline) {
        output = input;
        return true;
    }
    output = input;
    const int n = mb * L * operation::kCount;
    if ((int)input.size() != n) {
        return false;
    }
    std::vector<i128> node_duration(n);
    std::vector<long long> node_duration64(n);
    const i128 max_i64 = std::numeric_limits<long long>::max();
    i128 positive_duration_sum = 0;
    bool duration_sum_fits = true;
    for (int m = 0; m < mb; m++) {
        for (int l = 0; l < L; l++) {
            for (int o = 0; o < operation::kCount; o++) {
                int u = id(m, l, o, L);
                node_duration[u] = dur[l][o];
                if (dur[l][o] > 0) {
                    if (dur[l][o] > max_i64 - positive_duration_sum) {
                        duration_sum_fits = false;
                    } else if (duration_sum_fits) {
                        positive_duration_sum += dur[l][o];
                    }
                }
            }
        }
    }
    const i128 path_bound = positive_duration_sum + n;
    const bool sum_end_fits = path_bound <= max_i64 && (i128)n <= max_i64 / path_bound;
    bool int64_safe = retime_auto && duration_sum_fits && path_bound <= max_i64 && sum_end_fits &&
                      best_time >= 0 && best_time <= max_i64;
    if (int64_safe) {
        for (int u = 0; u < n; u++) {
            if (node_duration[u] < 0 || node_duration[u] > max_i64) {
                int64_safe = false;
                break;
            }
            node_duration64[u] = (long long)node_duration[u];
        }
    }
    std::vector<std::pair<int, int>> base_edges;
    auto edge = [&](int a, int b) { base_edges.push_back({a, b}); };
    for (int m = 0; m < mb; m++) {
        if ((m & limits::kOuterDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        for (int l = 0; l < L; l++) {
            operation_graph::append_layer_edges(
                m, l, L, [L](int mm, int ll, int op) { return id(mm, ll, op, L); }, edge);
        }
    }
    std::vector<i128> orig(n);
    for (auto& o : input) {
        orig[id(o.mb, o.l, o.op, L)] = o.start;
    }
    using Key = std::pair<int, int>;
    std::map<Key, std::vector<int>> seq;
    for (int m = 0; m < mb; m++) {
        if ((m & limits::kOuterDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        for (int l = 0; l < L; l++) {
            for (int o = 0; o < operation::kCount; o++) {
                if (dur[l][o] > 0) {
                    seq[{group[l], engine(o)}].push_back(id(m, l, o, L));
                }
            }
        }
    }
    for (auto& kv : seq) {
        std::sort(kv.second.begin(), kv.second.end(),
                  [&](int a, int b) { return std::tie(orig[a], a) < std::tie(orig[b], b); });
    }
    std::vector<std::vector<int>> base_out(n);
    std::vector<int> base_indegree(n, 0);
    for (auto [a, b] : base_edges) {
        base_out[a].push_back(b);
        base_indegree[b]++;
    }
    // Exact official closed-interval resource and memory legality check.
    std::vector<unsigned char> memory_always_ok(G, 1);
    for (int g = 0; g < G; g++) {
        int layers = 0;
        for (int l = 0; l < L; l++) {
            layers += (group[l] == g);
        }
        i128 comm_upper = 0;
        for (int l = 0; l < L; l++) {
            if (group[l] == g) {
                for (int o : operation::kCommunicationOperations) {
                    comm_upper = std::max(comm_upper, dur[l][o]);
                }
            }
        }
        i128 fixed_upper = (i128)layers * resident_per_layer +
                           operation::kMaxCommunicationBuffers * U + (i128)layers * mb * Ua;
        if (comm_upper == 0) {
            fixed_upper -= operation::kMaxCommunicationBuffers * U;
        }
        memory_always_ok[g] = fixed_upper <= M;
        stats.memory_fast_groups += memory_always_ok[g];
    }
    bool memory_all_fast = stats.memory_fast_groups == G;
    auto memory_ok = [&](const auto& st, const auto& en) {
        // Closed intervals overlap when one reservation ends exactly as another begins.
        auto peak_closed = [](std::vector<std::pair<i128, i128>>& a) {
            std::sort(a.begin(), a.end());
            std::multiset<i128> ends;
            int best = 0;
            for (size_t i = 0; i < a.size();) {
                size_t j = i;
                while (j < a.size() && a[j].first == a[i].first) {
                    j++;
                }
                while (!ends.empty() && *ends.begin() < a[i].first) {
                    ends.erase(ends.begin());
                }
                best = std::max(best, (int)ends.size() + (int)(j - i));
                for (size_t k = i; k < j; k++) {
                    ends.insert(a[k].second);
                }
                i = j;
            }
            return best;
        };
        for (int g = 0; g < G; g++) {
            if (memory_always_ok[g]) {
                continue;
            }
            int layers = 0;
            for (int l = 0; l < L; l++) {
                layers += (group[l] == g);
            }
            std::vector<std::pair<i128, i128>> acts, comms;
            for (int m = 0; m < mb; m++) {
                for (int l = 0; l < L; l++) {
                    if (group[l] == g) {
                        int b = id(m, l, 0, L);
                        acts.push_back({en[b + operation::kCombineForward],
                                        st[b + operation::kSharedBackward]});
                        for (int o : operation::kCommunicationOperations) {
                            if (dur[l][o] > 0) {
                                comms.push_back({st[b + o], en[b + o]});
                            }
                        }
                    }
                }
            }
            i128 used =
                (i128)layers * resident_per_layer + U * peak_closed(comms) + Ua * peak_closed(acts);
            if (used > M) {
                return false;
            }
        }
        return true;
    };
    auto run_typed = [&](const std::map<Key, std::vector<int>>& s, int gap,
                         std::vector<event_sched::Op>& cand, auto& tm, auto& sum_end,
                         auto best_secondary, const auto& duration) -> bool {
        std::vector<int> indeg = base_indegree, next(n, -1);
        std::vector<unsigned char> next_gap(n, 0);
        for (auto& kv : s) {
            auto& v = kv.second;
            int w = (kv.first.second == operation::kCommunicationEngine ? gap : 0);
            for (size_t j = 1; j < v.size(); j++) {
                next[v[j - 1]] = v[j];
                next_gap[v[j - 1]] = (unsigned char)w;
                indeg[v[j]]++;
            }
        }
        std::vector<int> q;
        q.reserve(n);
        for (int i = 0; i < n; i++) {
            if (!indeg[i]) {
                q.push_back(i);
            }
        }
        using Time = std::decay_t<decltype(tm)>;
        const Time time_limit = static_cast<Time>(best_time);
        std::vector<Time> st(n, 0), en(n, 0);
        int done = 0;
        tm = 0;
        sum_end = 0;
        for (size_t qi = 0; qi < q.size(); qi++) {
            if ((qi & limits::kInnerDeadlineCheckMask) == 0 &&
                std::chrono::steady_clock::now() >= deadline) {
                return false;
            }
            int u = q[qi];
            done++;
            en[u] = st[u] + duration[u];
            tm = std::max(tm, en[u]);
            if (tm > time_limit) {
                return false;
            }
            sum_end += en[u];
            for (int v : base_out[u]) {
                st[v] = std::max(st[v], en[u]);
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
            int v = next[u];
            if (v >= 0) {
                st[v] = std::max(st[v], en[u] + next_gap[u]);
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
        }
        if (done != n) {
            return false;
        }
        // Local polish alone permits equal Time when the secondary sum of end times falls.
        if (tm > time_limit || (tm == time_limit && sum_end >= best_secondary)) {
            return false;
        }
        if (!memory_ok(st, en)) {
            return false;
        }
        cand.clear();
        cand.reserve(n);
        for (int m = 0; m < mb; m++) {
            for (int l = 0; l < L; l++) {
                for (int o = 0; o < operation::kCount; o++) {
                    cand.push_back({st[id(m, l, o, L)], m, l, o});
                }
            }
        }
        std::sort(cand.begin(), cand.end(), [](auto& a, auto& b) {
            return std::tie(a.start, a.mb, a.l, a.op) < std::tie(b.start, b.mb, b.l, b.op);
        });
        return true;
    };
    auto run = [&](const std::map<Key, std::vector<int>>& s, int gap,
                   std::vector<event_sched::Op>& cand, i128& tm, i128& sum_end,
                   i128 best_secondary) -> bool {
        if (int64_safe && best_secondary >= 0 && best_secondary <= max_i64) {
            long long t64 = 0, sum64 = 0;
            bool ok =
                run_typed(s, gap, cand, t64, sum64, (long long)best_secondary, node_duration64);
            tm = t64;
            sum_end = sum64;
            return ok;
        }
        return run_typed(s, gap, cand, tm, sum_end, best_secondary, node_duration);
    };

    // Retiming current ordering for each candidate gap; only use it if legal and
    // faster. Try one gap first, then exact block enumeration on the critical path.
    std::map<Key, std::vector<int>> best_seq = seq;
    i128 resource_lb = 0;
    for (auto& kv : best_seq) {
        i128 load = 0;
        for (int z : kv.second) {
            load += dur[operation_graph::layer_of(z, L)][operation_graph::operation_of(z)];
        }
        resource_lb = std::max(resource_lb, load);
    }
    std::vector<event_sched::Op> cand;
    i128 tm, sum_end;
    int chosen_gap = 0;
    i128 best_secondary = 0;
    for (auto& o : input) {
        best_secondary += o.start + dur[o.l][o.op];
    }
    for (int gap = 0; gap <= (variant > 0 && memory_all_fast ? 0 : 1); gap++) {
        if (std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        bool ok = run(best_seq, gap, cand, tm, sum_end, best_secondary);
        stats.evaluated++;
        if (ok) {
            if (tm < best_time) {
                best_time = tm;
                stats.strict_improve++;
            } else {
                stats.tie_moves++;
            }
            best_secondary = sum_end;
            output = cand;
            chosen_gap = gap;
            stats.accepted++;
        }
    }
    // Find a longest path in the reusable base DAG plus current resource chains.
    std::vector<int> indeg = base_indegree, next(n, -1);
    std::vector<unsigned char> next_gap(n, 0);
    for (auto& kv : best_seq) {
        auto& v = kv.second;
        int w = (kv.first.second == operation::kCommunicationEngine ? chosen_gap : 0);
        for (size_t j = 1; j < v.size(); j++) {
            next[v[j - 1]] = v[j];
            next_gap[v[j - 1]] = (unsigned char)w;
            indeg[v[j]]++;
        }
    }
    std::vector<int> topo;
    {
        std::vector<int> q;
        q.reserve(n);
        for (int i = 0; i < n; i++) {
            if (!indeg[i]) {
                q.push_back(i);
            }
        }
        for (size_t qi = 0; qi < q.size(); qi++) {
            if ((qi & limits::kInnerDeadlineCheckMask) == 0 &&
                std::chrono::steady_clock::now() >= deadline) {
                return true;
            }
            int u = q[qi];
            topo.push_back(u);
            for (int v : base_out[u]) {
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
            int v = next[u];
            if (v >= 0 && --indeg[v] == 0) {
                q.push_back(v);
            }
        }
    }
    if ((int)topo.size() != n) {
        return true;
    }
    std::vector<i128> start(n, 0), finish(n, 0);
    std::vector<int> par(n, -1);
    for (int u : topo) {
        if ((u & limits::kInnerDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        int l = operation_graph::layer_of(u, L), o = operation_graph::operation_of(u);
        finish[u] = start[u] + dur[l][o];
        for (int v : base_out[u]) {
            i128 ns = finish[u];
            if (ns > start[v]) {
                start[v] = ns, par[v] = u;
            }
        }
        int v = next[u];
        if (v >= 0) {
            i128 ns = finish[u] + next_gap[u];
            if (ns > start[v]) {
                start[v] = ns, par[v] = u;
            }
        }
    }
    int end = 0;
    for (int u = 1; u < n; u++) {
        if (finish[u] > finish[end]) {
            end = u;
        }
    }
    std::vector<int> cp;
    for (int u = end; u >= 0; u = par[u]) {
        cp.push_back(u);
    }
    std::reverse(cp.begin(), cp.end());
    std::map<int, std::map<Key, std::vector<int>>> windows;
    for (size_t i = 0; i < cp.size();) {
        if ((i & limits::kInnerDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        int u = cp[i], l = operation_graph::layer_of(u, L), o = operation_graph::operation_of(u);
        if (dur[l][o] <= 0) {
            i++;
            continue;
        }
        Key k = {group[l], engine(o)};
        size_t j = i + 1;
        while (j < cp.size()) {
            int v = cp[j];
            int vl = operation_graph::layer_of(v, L), vo = operation_graph::operation_of(v);
            if (dur[vl][vo] <= 0 || Key{group[vl], engine(vo)} != k) {
                break;
            }
            j++;
        }
        auto it = best_seq.find(k);
        if (it != best_seq.end()) {
            std::map<int, int> pos;
            for (int p = 0; p < (int)it->second.size(); p++) {
                pos[it->second[p]] = p;
            }
            int lo = it->second.size(), hi = -1;
            for (size_t z = i; z < j; z++) {
                lo = std::min(lo, pos[cp[z]]);
                hi = std::max(hi, pos[cp[z]]);
            }
            for (int a = lo; a <= hi; a++) {
                for (int len = limits::kBlockLengthMin;
                     len <= limits::kBlockLengthMax && a + len <= hi + 1; len++) {
                    windows[len][k].push_back(a);
                }
            }
        }
        i = j;
    }
    // Try insertion moves first, interleaving resources and move distances.
    std::set<int> critical(cp.begin(), cp.end());
    auto try_seq = [&]() {
        if (resource_lb > best_time) {
            return;
        }
        for (int gap = 0; gap <= (variant > 0 && memory_all_fast ? 0 : 1); gap++) {
            if (stats.evaluated >= max_evaluations ||
                std::chrono::steady_clock::now() >= deadline) {
                stats.exhausted = false;
                return;
            }
            std::vector<event_sched::Op> cc;
            i128 t, s;
            bool ok = run(best_seq, gap, cc, t, s, best_secondary);
            stats.evaluated++;
            if (ok) {
                if (t < best_time) {
                    best_time = t;
                    stats.strict_improve++;
                } else {
                    stats.tie_moves++;
                }
                best_secondary = s;
                output.swap(cc);
                chosen_gap = gap;
                stats.accepted++;
            }
        }
    };
    auto insertion_base = best_seq;
    std::map<Key, std::vector<int>> critical_by_resource;
    for (auto& kv : insertion_base) {
        for (int z : kv.second) {
            if (critical.count(z)) {
                critical_by_resource[kv.first].push_back(z);
            }
        }
    }
    std::vector<int> distances, dirs;
    for (int d = 1; d <= limits::kDistanceRotationSpan; d++) {
        distances.push_back(d);
    }
    dirs = {-1, 1};
    if (variant > 0) {
        for (int d : {limits::kVariantDistanceStep0, limits::kVariantDistanceStep1,
                      limits::kVariantDistanceStep2, limits::kVariantDistanceStep3}) {
            distances.push_back(d);
        }
        std::rotate(distances.begin(),
                    distances.begin() +
                        ((variant * limits::kDistanceRotationMultiplier) % distances.size()),
                    distances.end());
        if (variant % 2) {
            std::reverse(dirs.begin(), dirs.end());
        }
    }
    std::vector<Key> resources;
    for (auto& kr : critical_by_resource) {
        resources.push_back(kr.first);
    }
    if (!resources.empty() && variant > 0) {
        std::rotate(resources.begin(),
                    resources.begin() +
                        ((variant * limits::kResourceRotationMultiplier) % resources.size()),
                    resources.end());
    }
    if (variant > 0) {
        for (auto& kr : critical_by_resource) {
            auto& ops = kr.second;
            if (!ops.empty()) {
                std::rotate(
                    ops.begin(),
                    ops.begin() + ((variant * limits::kOperationRotationMultiplier) % ops.size()),
                    ops.end());
                if (variant % 2) {
                    std::reverse(ops.begin(), ops.end());
                }
            }
        }
    }
    for (int distance : distances) {
        if (variant > 0 && variant % limits::kVariantCycle == 0) {
            break;
        }
        if (!stats.exhausted) {
            break;
        }
        for (int dir : dirs) {
            for (const auto& resource : resources) {
                auto& kr = *critical_by_resource.find(resource);
                for (int z : kr.second) {
                    if (!stats.exhausted) {
                        break;
                    }
                    auto& w = best_seq[kr.first];
                    auto itp = std::find(w.begin(), w.end(), z);
                    if (itp == w.end()) {
                        continue;
                    }
                    int p = itp - w.begin(), q = p + dir * distance;
                    if (q < 0 || q >= (int)w.size()) {
                        continue;
                    }
                    auto old = w;
                    w.erase(w.begin() + p);
                    w.insert(w.begin() + q, z);
                    long long before = stats.accepted;
                    try_seq();
                    if (stats.accepted == before) {
                        w.swap(old);
                    }
                }
            }
        }
    }
    // For each block size, spread the first pass across all resources before
    // completing additional windows. Each window enumerates every permutation.
    std::vector<int> lengths;
    for (int len = limits::kBlockLengthMin; len <= limits::kBlockLengthMax; ++len) {
        lengths.push_back(len);
    }
    if (variant > 0) {
        std::rotate(lengths.begin(), lengths.begin() + ((variant / 4) % lengths.size()),
                    lengths.end());
    }
    auto unrank_permutation = [](std::vector<int> items, size_t rank) {
        std::vector<int> result;
        result.reserve(items.size());
        for (size_t left = items.size(); left > 0; left--) {
            size_t factorial = 1;
            for (size_t k = 2; k < left; k++) {
                factorial *= k;
            }
            size_t index = rank / factorial;
            rank %= factorial;
            result.push_back(items[index]);
            items.erase(items.begin() + index);
        }
        return result;
    };
    for (int len : lengths) {
        if (!stats.exhausted) {
            break;
        }
        auto wit = windows.find(len);
        if (wit == windows.end()) {
            continue;
        }
        auto& by_resource = wit->second;
        size_t max_windows = 0;
        for (auto& kv : by_resource) {
            max_windows = std::max(max_windows, kv.second.size());
        }
        std::vector<Key> window_resources;
        for (auto& kv : by_resource) {
            window_resources.push_back(kv.first);
        }
        if (variant > 0) {
            for (auto& kv : by_resource) {
                if (!kv.second.empty()) {
                    std::rotate(kv.second.begin(), kv.second.begin() + (variant % kv.second.size()),
                                kv.second.end());
                }
            }
            if (!window_resources.empty()) {
                std::rotate(window_resources.begin(),
                            window_resources.begin() +
                                ((variant * limits::kResourceRotationMultiplier + len) %
                                 window_resources.size()),
                            window_resources.end());
            }
        }
        for (size_t wi = 0; wi < max_windows && stats.exhausted; wi++) {
            for (const Key& resource : window_resources) {
                auto& kv = *by_resource.find(resource);
                if (wi >= kv.second.size()) {
                    continue;
                }
                int a = kv.second[wi];
                if (stats.evaluated >= max_evaluations ||
                    std::chrono::steady_clock::now() >= deadline) {
                    stats.exhausted = false;
                    break;
                }
                auto it = best_seq.find(kv.first);
                if (it == best_seq.end() || a + len > (int)it->second.size()) {
                    continue;
                }
                auto& v = it->second;
                auto block = std::vector<int>(v.begin() + a, v.begin() + a + len);
                auto sorted = block;
                std::sort(sorted.begin(), sorted.end());
                size_t permutation_count = 1;
                for (int k = 2; k <= len; k++) {
                    permutation_count *= k;
                }
                size_t start_rank = 0;
                if (variant > 0) {
                    start_rank = ((size_t)variant * limits::kPermutationStartMultiplier +
                                  wi * limits::kPermutationWindowStride + (size_t)a) %
                                 permutation_count;
                }
                auto start_perm = variant > 0 ? unrank_permutation(sorted, start_rank) : sorted;
                auto perm = start_perm;
                auto accepted_block = block;
                do {
                    if (perm != block) {
                        std::copy(perm.begin(), perm.end(), v.begin() + a);
                        long long before = stats.accepted;
                        try_seq();
                        if (stats.accepted > before) {
                            accepted_block = perm;
                        } else {
                            std::copy(accepted_block.begin(), accepted_block.end(), v.begin() + a);
                        }
                    }
                    if (!stats.exhausted) {
                        break;
                    }
                    if (!std::next_permutation(perm.begin(), perm.end())) {
                        perm = sorted;
                    }
                    if (perm == start_perm) {
                        break;
                    }
                } while (true);
                if (!stats.exhausted) {
                    break;
                }
            }
        }
    }

    return true;
}
}  // namespace local_engine_polish
