#include "layout_bound_search.hpp"

#include "../core/operation_graph.hpp"
#include "../io/numeric.hpp"
#include "../placement/expert_mapping.hpp"
#include "../scheduling/event_scheduler.hpp"
#include "../scheduling/schedule_api.hpp"
#include "schedule_validation.hpp"

namespace solver {
namespace {
using namespace std;
using Clock = chrono::steady_clock;
using i128 = __int128_t;
constexpr i128 kInf = search_limits::kInfiniteTime;
constexpr int kConstraintThresholds = 7;
constexpr int kSeedLimit = 8;
constexpr int kMaxLayoutsPerPlacement = 12;
constexpr size_t kMaxFoldCacheEntries = 1'000'000;

struct ResourceConstraint {
    i128 release = 0;
    i128 tail = 0;
    int engine = 0;
    vector<i128> prefix;
};

struct LayoutSeed {
    Candidate candidate;
    int G = 0;
    int K = 0;
    vector<int> cuts;
    i128 lower_bound = kInf;
    string source;
};

struct BoundModel {
    vector<ResourceConstraint> constraints;
    i128 resident_per_layer = 0;
};

struct HeadTailData {
    vector<i128> head;
    vector<i128> tail;
};

struct FoldParent {
    int a = -1;
    int b = -1;
};

struct SeedSpec {
    int G = 0;
    int K = 0;
    vector<int> cuts;
};

SeedSpec schedule_seed_spec(const ScheduleResult& result) {
    return {result.G, result.K, result.cuts};
}

bool is_comm(int op) {
    for (int q : operation::kCommunicationOperations) {
        if (q == op) {
            return true;
        }
    }
    return false;
}

bool expired(Clock::time_point deadline) {
    return Clock::now() >= deadline;
}

vector<int> make_group_map(const vector<int>& cuts, int G, int L) {
    const int K = static_cast<int>(cuts.size()) - 1;
    vector<int> group(L, -1);
    for (int block = 0; block < K; ++block) {
        const int g = (K == G || block < G) ? block : 2 * G - 1 - block;
        for (int layer = cuts[block]; layer < cuts[block + 1]; ++layer) {
            group[layer] = g;
        }
    }
    return group;
}

vector<int> count_layers(const vector<int>& group, int G) {
    vector<int> counts(G);
    for (int g : group) {
        if (g >= 0 && g < G) {
            ++counts[g];
        }
    }
    return counts;
}

vector<i128> sample_thresholds(vector<i128> values) {
    sort(values.begin(), values.end());
    values.erase(unique(values.begin(), values.end()), values.end());
    vector<i128> chosen{0};
    if (values.empty()) {
        return chosen;
    }
    if (static_cast<int>(values.size()) <= kConstraintThresholds) {
        chosen.insert(chosen.end(), values.begin(), values.end());
    } else {
        for (int q = 0; q < kConstraintThresholds; ++q) {
            size_t at = static_cast<size_t>(q) * (values.size() - 1) /
                        static_cast<size_t>(kConstraintThresholds - 1);
            chosen.push_back(values[at]);
        }
    }
    sort(chosen.begin(), chosen.end());
    chosen.erase(unique(chosen.begin(), chosen.end()), chosen.end());
    return chosen;
}

bool build_head_tail(const InputData& x, const vector<array<i128, operation::kCount>>& dur,
                     HeadTailData& result, Clock::time_point deadline) {
    const int L = x.L;
    const int nodes = L * operation::kCount;
    vector<vector<int>> pred(nodes), succ(nodes);
    auto id = [L](int, int layer, int op) { return layer * operation::kCount + op; };
    for (int layer = 0; layer < L; ++layer) {
        operation_graph::append_layer_edges(0, layer, L, id, [&](int a, int b) {
            succ[a].push_back(b);
            pred[b].push_back(a);
        });
        if ((layer & 7) == 0 && expired(deadline)) {
            return false;
        }
    }

    vector<int> indegree(nodes);
    for (int node = 0; node < nodes; ++node) {
        indegree[node] = static_cast<int>(pred[node].size());
    }
    vector<int> ready;
    for (int node = 0; node < nodes; ++node) {
        if (indegree[node] == 0) {
            ready.push_back(node);
        }
    }
    vector<int> order;
    order.reserve(nodes);
    for (size_t at = 0; at < ready.size(); ++at) {
        const int node = ready[at];
        order.push_back(node);
        for (int next : succ[node]) {
            if (--indegree[next] == 0) {
                ready.push_back(next);
            }
        }
    }
    if (static_cast<int>(order.size()) != nodes) {
        return false;
    }

    const int words = (nodes + 63) / 64;
    vector<vector<uint64_t>> ancestors(nodes, vector<uint64_t>(words));
    vector<vector<uint64_t>> descendants(nodes, vector<uint64_t>(words));
    for (int node : order) {
        for (int p : pred[node]) {
            ancestors[node][p / 64] |= uint64_t{1} << (p % 64);
            for (int w = 0; w < words; ++w) {
                ancestors[node][w] |= ancestors[p][w];
            }
        }
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        const int node = *it;
        for (int s : succ[node]) {
            descendants[node][s / 64] |= uint64_t{1} << (s % 64);
            for (int w = 0; w < words; ++w) {
                descendants[node][w] |= descendants[s][w];
            }
        }
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }

    result.head.assign(nodes, 0);
    result.tail.assign(nodes, 0);
    auto resource_work = [&](const vector<uint64_t>& related, int layer, int engine,
                             const vector<i128>& releases) {
        vector<i128> values;
        for (int word = 0; word < words; ++word) {
            uint64_t bits = related[word];
            while (bits != 0) {
                const int bit = __builtin_ctzll(bits);
                const int n = word * 64 + bit;
                bits &= bits - 1;
                if (n >= nodes || n / operation::kCount != layer) {
                    continue;
                }
                const int op = n % operation::kCount;
                if (dur[layer][op] > 0 && static_cast<int>(is_comm(op)) == engine) {
                    values.push_back(releases[n]);
                }
            }
        }
        if (values.empty()) {
            return i128{0};
        }
        sort(values.begin(), values.end());
        values.erase(unique(values.begin(), values.end()), values.end());
        i128 bound = 0;
        for (i128 release : values) {
            i128 work = 0;
            for (int word = 0; word < words; ++word) {
                uint64_t bits = related[word];
                while (bits != 0) {
                    const int bit = __builtin_ctzll(bits);
                    const int n = word * 64 + bit;
                    bits &= bits - 1;
                    if (n >= nodes || n / operation::kCount != layer) {
                        continue;
                    }
                    const int op = n % operation::kCount;
                    if (dur[layer][op] > 0 && static_cast<int>(is_comm(op)) == engine &&
                        releases[n] >= release) {
                        work += dur[layer][op];
                    }
                }
            }
            bound = max(bound, release + work);
        }
        return bound;
    };

    for (int node : order) {
        i128 value = 0;
        for (int p : pred[node]) {
            value = max(value, result.head[p] + dur[p / operation::kCount][p % operation::kCount]);
        }
        const int layer = node / operation::kCount;
        const int op = node % operation::kCount;
        value = max(value, resource_work(ancestors[node], layer, is_comm(op), result.head));
        result.head[node] = value;
    }
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        const int node = *it;
        i128 value = 0;
        for (int s : succ[node]) {
            value = max(value, result.tail[s] + dur[s / operation::kCount][s % operation::kCount]);
        }
        const int layer = node / operation::kCount;
        const int op = node % operation::kCount;
        value = max(value, resource_work(descendants[node], layer, is_comm(op), result.tail));
        result.tail[node] = value;
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }
    return true;
}

bool build_bound_model(const InputData& x, const Candidate& c,
                       const vector<array<i128, operation::kCount>>& dur, BoundModel& model,
                       Clock::time_point deadline) {
    model.resident_per_layer = (x.E / c.P) * x.Z + x.Zs;
    if (model.resident_per_layer < 0) {
        return false;
    }
    HeadTailData ht;
    if (!build_head_tail(x, dur, ht, deadline)) {
        return false;
    }
    vector<i128> releases[2], tails[2];
    for (int layer = 0; layer < x.L; ++layer) {
        for (int op = 0; op < operation::kCount; ++op) {
            if (dur[layer][op] <= 0) {
                continue;
            }
            const int e = is_comm(op);
            releases[e].push_back(ht.head[layer * operation::kCount + op]);
            tails[e].push_back(ht.tail[layer * operation::kCount + op]);
        }
    }
    vector<i128> rs[2], qs[2];
    for (int e = 0; e < 2; ++e) {
        rs[e] = sample_thresholds(move(releases[e]));
        qs[e] = sample_thresholds(move(tails[e]));
    }
    for (int e = 0; e < 2; ++e) {
        for (i128 R : rs[e]) {
            for (i128 Q : qs[e]) {
                ResourceConstraint constraint;
                constraint.release = R;
                constraint.tail = Q;
                constraint.engine = e;
                constraint.prefix.assign(x.L + 1, 0);
                for (int layer = 0; layer < x.L; ++layer) {
                    i128 weight = 0;
                    for (int op = 0; op < operation::kCount; ++op) {
                        const int node = layer * operation::kCount + op;
                        if (static_cast<int>(is_comm(op)) == e && dur[layer][op] > 0 &&
                            ht.head[node] >= R && ht.tail[node] >= Q) {
                            weight += dur[layer][op];
                        }
                    }
                    constraint.prefix[layer + 1] = constraint.prefix[layer] + weight;
                }
                if (constraint.prefix.back() > 0) {
                    model.constraints.push_back(move(constraint));
                }
                if (expired(deadline)) {
                    return false;
                }
            }
        }
    }
    return !model.constraints.empty();
}

vector<vector<i128>> segment_costs(const InputData& x, const BoundModel& model,
                                   Clock::time_point deadline) {
    const int n = x.L + 1;
    vector<vector<i128>> costs(n, vector<i128>(n, kInf));
    for (int i = 0; i < x.L; ++i) {
        for (int j = i + 1; j <= x.L; ++j) {
            if ((i128)(j - i) * model.resident_per_layer > x.M) {
                continue;
            }
            i128 best = 0;
            for (const ResourceConstraint& c : model.constraints) {
                const i128 work = c.prefix[j] - c.prefix[i];
                if (work > 0) {
                    best = max(best, c.release + c.tail + (i128)x.mb * work);
                }
            }
            costs[i][j] = best;
        }
        if ((i & 3) == 0 && expired(deadline)) {
            return {};
        }
    }
    return costs;
}

vector<LayoutSeed> contiguous_dp(const InputData& x, const Candidate& c, const BoundModel& model,
                                 int max_groups, Clock::time_point deadline) {
    vector<LayoutSeed> out;
    const int n = x.L + 1;
    auto cost = segment_costs(x, model, deadline);
    if (cost.empty()) {
        return out;
    }
    vector<vector<i128>> dp(max_groups + 1, vector<i128>(n, kInf));
    vector<vector<int>> parent(max_groups + 1, vector<int>(n, -1));
    dp[0][0] = 0;
    for (int g = 1; g <= max_groups; ++g) {
        for (int j = g; j <= x.L; ++j) {
            for (int i = g - 1; i < j; ++i) {
                if (dp[g - 1][i] >= kInf || cost[i][j] >= kInf) {
                    continue;
                }
                const i128 value = max(dp[g - 1][i], cost[i][j]);
                if (value < dp[g][j]) {
                    dp[g][j] = value;
                    parent[g][j] = i;
                }
            }
            if ((j & 15) == 0 && expired(deadline)) {
                return out;
            }
        }
        if (dp[g][x.L] < kInf) {
            vector<int> cuts(g + 1);
            int at = x.L;
            cuts[g] = x.L;
            bool valid = true;
            for (int q = g; q > 0; --q) {
                const int prev = parent[q][at];
                if (prev < 0) {
                    valid = false;
                    break;
                }
                cuts[q - 1] = prev;
                at = prev;
            }
            if (valid) {
                LayoutSeed seed{c, g, g, cuts, dp[g][x.L], "threshold_dp_contiguous"};
                seed.candidate.V = g;
                seed.candidate.cuts = cuts;
                out.push_back(move(seed));
            }
        }
    }
    return out;
}

size_t choose4(int n) {
    if (n < 4) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) * (n - 2) * (n - 3) / 24;
}

size_t choose3(int n) {
    if (n < 3) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) * (n - 2) / 6;
}

size_t choose2(int n) {
    if (n < 2) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) / 2;
}

size_t colex_rank(int i, int a, int b, int j) {
    return choose4(j) + choose3(b) + choose2(a) + static_cast<size_t>(i);
}

vector<LayoutSeed> folded_dp(const InputData& x, const Candidate& c, const BoundModel& model,
                             int max_groups, const vector<vector<i128>>& segment_cost,
                             Clock::time_point deadline) {
    vector<LayoutSeed> out;
    const int n = x.L + 1;
    if (max_groups <= 0 || segment_cost.empty()) {
        return out;
    }
    const size_t cache_size = choose4(n);
    if (cache_size > kMaxFoldCacheEntries) {
        return out;
    }
    vector<i128> outside_cache(cache_size, kInf);
    vector<uint8_t> computed(cache_size, 0);
    auto outside_cost = [&](int i, int a, int b, int j) {
        const size_t index = colex_rank(i, a, b, j);
        if (!computed[index]) {
            const int layers = (a - i) + (j - b);
            if ((i128)layers * model.resident_per_layer > x.M) {
                outside_cache[index] = kInf;
            } else {
                i128 best = 0;
                for (const ResourceConstraint& q : model.constraints) {
                    const i128 work = q.prefix[a] - q.prefix[i] + q.prefix[j] - q.prefix[b];
                    if (work > 0) {
                        best = max(best, q.release + q.tail + (i128)x.mb * work);
                    }
                }
                outside_cache[index] = best;
            }
            computed[index] = 1;
        }
        return outside_cache[index];
    };

    vector<vector<i128>> previous(n, vector<i128>(n, kInf));
    for (int i = 0; i < x.L; ++i) {
        for (int j = i + 2; j <= x.L; ++j) {
            previous[i][j] = segment_cost[i][j];
        }
    }
    const size_t parent_size = static_cast<size_t>(max_groups + 1) * n * n;
    vector<FoldParent> parents(parent_size);
    auto pindex = [n](int g, int i, int j) { return (static_cast<size_t>(g) * n + i) * n + j; };
    size_t transitions = 0;
    for (int g = 1; g <= max_groups; ++g) {
        if (g >= 2) {
            vector<vector<i128>> current(n, vector<i128>(n, kInf));
            for (int i = 0; i + 2 * g <= x.L; ++i) {
                for (int j = i + 2 * g; j <= x.L; ++j) {
                    for (int a = i + 1; a + 2 * (g - 1) < j; ++a) {
                        const int b_min = a + 2 * (g - 1);
                        for (int b = b_min; b < j; ++b) {
                            if (((++transitions) & 255U) == 0U && expired(deadline)) {
                                return out;
                            }
                            const i128 inner = previous[a][b];
                            if (inner >= kInf) {
                                continue;
                            }
                            const i128 outer = outside_cost(i, a, b, j);
                            if (outer >= kInf) {
                                continue;
                            }
                            const i128 value = max(inner, outer);
                            if (value < current[i][j]) {
                                current[i][j] = value;
                                parents[pindex(g, i, j)] = {a, b};
                            }
                        }
                    }
                    if ((j & 3) == 0 && expired(deadline)) {
                        return out;
                    }
                }
            }
            previous.swap(current);
        }
        if (previous[0][x.L] < kInf) {
            vector<pair<int, int>> left(max_groups), right(max_groups);
            auto recover = [&](auto&& self, int q, int i, int j) -> bool {
                const int group = g - q;
                if (q == 1) {
                    const int mid = i + (j - i) / 2;
                    if (mid <= i || mid >= j) {
                        return false;
                    }
                    left[group] = {i, mid};
                    right[group] = {mid, j};
                    return true;
                }
                const FoldParent split = parents[pindex(q, i, j)];
                if (split.a < 0) {
                    return false;
                }
                left[group] = {i, split.a};
                right[group] = {split.b, j};
                return self(self, q - 1, split.a, split.b);
            };
            if (recover(recover, g, 0, x.L)) {
                vector<int> cuts;
                cuts.reserve(2 * g + 1);
                cuts.push_back(0);
                for (int q = 0; q < g; ++q) {
                    cuts.push_back(left[q].second);
                }
                for (int q = g - 1; q >= 0; --q) {
                    cuts.push_back(right[q].second);
                }
                if (static_cast<int>(cuts.size()) == 2 * g + 1 && cuts.back() == x.L) {
                    LayoutSeed seed{c, g, 2 * g, cuts, previous[0][x.L], "threshold_dp_folded"};
                    seed.candidate.V = 2 * g;
                    seed.candidate.cuts = cuts;
                    out.push_back(move(seed));
                }
            }
        }
        if (expired(deadline)) {
            return out;
        }
    }
    return out;
}

bool valid_cuts(const vector<int>& cuts, int L, int G, int K) {
    if (K != G && K != 2 * G) {
        return false;
    }
    if (static_cast<int>(cuts.size()) != K + 1 || cuts.front() != 0 || cuts.back() != L) {
        return false;
    }
    for (int j = 1; j <= K; ++j) {
        if (cuts[j] <= cuts[j - 1]) {
            return false;
        }
    }
    return true;
}

bool valid_candidate_map(const InputData& x, const Candidate& candidate) {
    if (candidate.P <= 0 || candidate.map.size() != static_cast<size_t>(x.L)) {
        return false;
    }
    for (const vector<int>& row : candidate.map) {
        if (row.size() != static_cast<size_t>(x.E)) {
            return false;
        }
        for (int rank : row) {
            if (rank < 0 || rank >= candidate.P) {
                return false;
            }
        }
    }
    return true;
}

i128 layout_bound(const InputData& x, const BoundModel& model, const vector<int>& cuts, int G,
                  Clock::time_point deadline = Clock::time_point::max()) {
    const int K = static_cast<int>(cuts.size()) - 1;
    vector<vector<pair<int, int>>> blocks(G);
    for (int j = 0; j < K; ++j) {
        const int g = (K == G || j < G) ? j : 2 * G - 1 - j;
        blocks[g].push_back({cuts[j], cuts[j + 1]});
    }
    i128 value = 0;
    for (const auto& group_blocks : blocks) {
        int layers = 0;
        for (auto [a, b] : group_blocks) {
            layers += b - a;
        }
        if (layers * model.resident_per_layer > x.M) {
            return kInf;
        }
        for (const ResourceConstraint& constraint : model.constraints) {
            i128 work = 0;
            for (auto [a, b] : group_blocks) {
                work += constraint.prefix[b] - constraint.prefix[a];
            }
            if (work > 0) {
                value = max(value, constraint.release + constraint.tail + (i128)x.mb * work);
            }
        }
        if (expired(deadline)) {
            return kInf;
        }
    }
    return value;
}

void add_layout(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                const Candidate& c, int G, const vector<int>& cuts, const string& source,
                Clock::time_point deadline = Clock::time_point::max()) {
    if (expired(deadline)) {
        return;
    }
    const int K = static_cast<int>(cuts.size()) - 1;
    if (G <= 0 || G > x.N * x.S / c.P || !valid_cuts(cuts, x.L, G, K)) {
        return;
    }
    for (const LayoutSeed& old : layouts) {
        if (old.candidate.P == c.P && old.G == G && old.K == K && old.cuts == cuts) {
            return;
        }
    }
    LayoutSeed seed{c, G, K, cuts, layout_bound(x, model, cuts, G, deadline), source};
    seed.candidate.V = K;
    seed.candidate.cuts = cuts;
    if (seed.lower_bound < kInf) {
        layouts.push_back(move(seed));
    }
}

void seed_neighborhood(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                       const Candidate& c, int G, int K, const vector<int>& cuts,
                       Clock::time_point deadline = Clock::time_point::max()) {
    add_layout(layouts, x, model, c, G, cuts, "placement_seed", deadline);
    if (K == 2 * G) {
        for (int j = 1; j < G; ++j) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                moved[K - j] += delta;
                add_layout(layouts, x, model, c, G, moved, "mirror_pair_shift", deadline);
            }
        }
        vector<int> selected;
        for (int j = 1; j < G; ++j) {
            if (j <= 3 || j >= G - 3 || j % max(1, G / 4) == 0) {
                selected.push_back(j);
            }
        }
        if (selected.size() > 8) {
            vector<int> sampled;
            for (int q = 0; q < 8; ++q) {
                sampled.push_back(selected[q * (selected.size() - 1) / 7]);
            }
            selected.swap(sampled);
        }
        for (size_t a = 0; a < selected.size(); ++a) {
            if (expired(deadline)) {
                return;
            }
            for (size_t b = a + 1; b < selected.size(); ++b) {
                for (int da : {-1, 1}) {
                    for (int db : {-1, 1}) {
                        vector<int> moved = cuts;
                        const int j = selected[a];
                        const int k = selected[b];
                        moved[j] += da;
                        moved[K - j] += da;
                        moved[k] += db;
                        moved[K - k] += db;
                        add_layout(layouts, x, model, c, G, moved, "mirror_two_pair_shift",
                                   deadline);
                    }
                }
            }
        }
        vector<int> single_positions;
        for (int j : {1, 2, G - 1, G, G + 1, K - 2, K - 1}) {
            if (j >= 1 && j < K &&
                find(single_positions.begin(), single_positions.end(), j) ==
                    single_positions.end()) {
                single_positions.push_back(j);
            }
        }
        for (int j : single_positions) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                add_layout(layouts, x, model, c, G, moved, "folded_single_cut_shift", deadline);
            }
        }
    } else {
        for (int j = 1; j < K; ++j) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                add_layout(layouts, x, model, c, G, moved, "single_cut_shift", deadline);
            }
        }
    }
}

void interpolate_layouts(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                         const Candidate& c, const LayoutSeed& old, const LayoutSeed& fresh,
                         Clock::time_point deadline = Clock::time_point::max()) {
    const LayoutSeed old_copy = old;
    const LayoutSeed fresh_copy = fresh;
    if (old_copy.G != fresh_copy.G || old_copy.K != fresh_copy.K ||
        old_copy.candidate.P != fresh_copy.candidate.P) {
        return;
    }
    for (int numerator : {1, 2, 3, 4, 5, 7, 8, 9, 11, 12, 13, 15}) {
        if (expired(deadline)) {
            return;
        }
        constexpr int denominator = 16;
        vector<int> cuts(old_copy.K + 1);
        cuts[0] = 0;
        cuts[old_copy.K] = x.L;
        for (int j = 1; j < old_copy.K; ++j) {
            const i128 value = (i128)(denominator - numerator) * old_copy.cuts[j] +
                               (i128)numerator * fresh_copy.cuts[j];
            cuts[j] = static_cast<int>((value + denominator / 2) / denominator);
        }
        for (int j = 1; j < old_copy.K; ++j) {
            cuts[j] = max(cuts[j], cuts[j - 1] + 1);
        }
        for (int j = old_copy.K - 1; j > 0; --j) {
            cuts[j] = min(cuts[j], cuts[j + 1] - 1);
        }
        add_layout(layouts, x, model, c, old_copy.G, cuts, "seed_dp_interpolation", deadline);
    }
}

bool build_memory_caps(const InputData& x, const Candidate& c, const vector<int>& group,
                       const vector<int>& group_layers,
                       const vector<array<i128, operation::kCount>>& dur, vector<int>& caps,
                       vector<int>& buffers) {
    const int G = static_cast<int>(group_layers.size());
    const i128 resident = (x.E / c.P) * x.Z + x.Zs;
    caps.assign(G, 0);
    buffers.assign(G, 0);
    for (int g = 0; g < G; ++g) {
        bool has_comm = false;
        for (int layer = 0; layer < x.L; ++layer) {
            if (group[layer] != g) {
                continue;
            }
            for (int op : operation::kCommunicationOperations) {
                has_comm = has_comm || dur[layer][op] > 0;
            }
        }
        const int b = has_comm ? 1 : 0;
        const i128 available = x.M - (i128)group_layers[g] * resident - (has_comm ? x.U : 0);
        if (available < 0) {
            return false;
        }
        buffers[g] = b;
        if (x.Ua > 0) {
            caps[g] = static_cast<int>(min<i128>(available / x.Ua, (i128)x.mb * group_layers[g]));
        } else {
            caps[g] = x.mb * group_layers[g];
        }
        if (caps[g] < group_layers[g]) {
            return false;
        }
    }
    return true;
}

bool same_layout(const ScheduleResult& a, const ScheduleResult& b) {
    return a.c.P == b.c.P && a.G == b.G && a.K == b.K && a.cuts == b.cuts;
}

void normalize_schedule_order(vector<event_sched::Op>& ops) {
    stable_sort(ops.begin(), ops.end(), [](const event_sched::Op& a, const event_sched::Op& b) {
        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
    });
}

void retain_result(vector<ScheduleResult>& results, ScheduleResult result, ScheduleResult& best) {
    if (result.time < best.time) {
        best = result;
    }
    for (ScheduleResult& old : results) {
        if (same_layout(old, result)) {
            if (result.time < old.time) {
                old = move(result);
            }
            return;
        }
    }
    results.push_back(move(result));
}

bool evaluate_layout(const InputData& x, const LayoutSeed& seed,
                     const vector<array<i128, operation::kCount>>& dur, Clock::time_point deadline,
                     ScheduleResult& result) {
    if (expired(deadline)) {
        return false;
    }
    const vector<int> group = make_group_map(seed.cuts, seed.G, x.L);
    const vector<int> group_layers = count_layers(group, seed.G);
    if (any_of(group_layers.begin(), group_layers.end(), [](int n) { return n <= 0; })) {
        return false;
    }
    vector<int> caps, buffers;
    const bool event_memory_ok =
        build_memory_caps(x, seed.candidate, group, group_layers, dur, caps, buffers);

    result.c = seed.candidate;
    result.c.cuts = seed.cuts;
    result.c.V = seed.K;
    result.G = seed.G;
    result.K = seed.K;
    result.cuts = seed.cuts;
    result.group = group;
    result.time = kInf;
    scheduling::ProblemView problem{x.mb, x.L, seed.G, group, dur, group_layers};

    auto accept = [&](vector<event_sched::Op>& ops, i128 time) {
        if (time >= result.time ||
            ops.size() != static_cast<size_t>(x.mb * x.L * operation::kCount)) {
            return;
        }
        ScheduleResult trial = result;
        trial.time = time;
        trial.ops = ops;
        normalize_schedule_order(trial.ops);
        if (is_feasible_schedule(x, trial)) {
            result = move(trial);
        }
    };

    if (event_memory_ok) {
        for (int mode : {0, 1}) {
            if (expired(deadline)) {
                break;
            }
            vector<event_sched::Op> ops;
            i128 time = kInf;
            scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
            scheduling::EventConfig config;
            config.activation_capacity = &caps;
            config.communication_buffers = &buffers;
            config.window = 0;
            config.mode = mode;
            scheduling::ScheduleOutput output{ops, time};
            if (scheduler.run(config, output)) {
                accept(ops, time);
            }
        }
    }

    vector<scheduling::ListConfig> configs(1);
    configs[0].window = x.mb;
    configs[0].variant = 0;
    configs[0].fill_gaps = true;
    scheduling::ListConfig wave_a;
    wave_a.window = x.mb;
    wave_a.fill_gaps = true;
    wave_a.wave_rank = true;
    wave_a.rank_mode = 2;
    wave_a.rank_a = 1;
    wave_a.rank_b = 1;
    wave_a.pitch_numerator = 2;
    wave_a.pitch_denominator = 1;
    wave_a.duration_head = 1;
    wave_a.weight_gradient_order = 0;
    configs.push_back(wave_a);
    scheduling::ListConfig wave_b = wave_a;
    wave_b.pitch_numerator = 4;
    wave_b.pitch_denominator = 3;
    wave_b.duration_head = 2;
    wave_b.weight_gradient_order = 1;
    configs.push_back(wave_b);
    for (const scheduling::ListConfig& config : configs) {
        if (expired(deadline)) {
            break;
        }
        vector<event_sched::Op> ops;
        i128 time = kInf;
        scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
        scheduling::ScheduleOutput output{ops, time};
        if (scheduler.run(config, output)) {
            accept(ops, time);
        }
    }
    return result.time < kInf;
}

}  // namespace

vector<ScheduleResult> search_layout_bounds(const InputData& x,
                                            const vector<PartitionCandidate>& placements,
                                            ScheduleResult& best,
                                            chrono::steady_clock::time_point deadline) {
    vector<ScheduleResult> results;
    if (best.time < kInf) {
        ScheduleResult normalized_best = best;
        normalize_schedule_order(normalized_best.ops);
        if (is_feasible_schedule(x, normalized_best)) {
            best = normalized_best;
            results.push_back(move(normalized_best));
        }
    }
    if (expired(deadline)) {
        return results;
    }

    struct PlacementWork {
        int P = 0;
        Candidate representative;
        vector<SeedSpec> seeds;
    };
    vector<PlacementWork> work;
    auto add_candidate = [&](const Candidate& candidate) {
        if (!valid_candidate_map(x, candidate) || candidate.P > min(x.E, x.N * x.S) ||
            x.E % candidate.P != 0 || (x.S % candidate.P != 0 && candidate.P % x.S != 0) ||
            candidate.V > x.N * x.S / candidate.P ||
            candidate.V != static_cast<int>(candidate.cuts.size()) - 1 ||
            !valid_cuts(candidate.cuts, x.L, candidate.V, candidate.V)) {
            return;
        }
        auto it = find_if(work.begin(), work.end(),
                          [&](const PlacementWork& item) { return item.P == candidate.P; });
        if (it == work.end()) {
            PlacementWork item;
            item.P = candidate.P;
            item.representative = candidate;
            item.seeds.push_back({candidate.V, candidate.V, candidate.cuts});
            work.push_back(move(item));
        } else {
            for (const SeedSpec& old : it->seeds) {
                if (old.G == candidate.V && old.K == candidate.V && old.cuts == candidate.cuts) {
                    return;
                }
            }
            it->seeds.push_back({candidate.V, candidate.V, candidate.cuts});
        }
    };
    for (const PartitionCandidate& placement : placements) {
        add_candidate(placement.best_v);
        add_candidate(placement.max_v);
    }
    if (valid_candidate_map(x, best.c)) {
        auto it = find_if(work.begin(), work.end(),
                          [&](const PlacementWork& item) { return item.P == best.c.P; });
        if (it == work.end()) {
            PlacementWork item;
            item.P = best.c.P;
            item.representative = best.c;
            work.push_back(move(item));
            it = prev(work.end());
        } else if (best.c.map.size() == static_cast<size_t>(x.L)) {
            // All layouts for one P use one MAP, so durations and bounds agree.
            it->representative = best.c;
        }
        if (best.G > 0 && (best.K == best.G || best.K == 2 * best.G) &&
            best.cuts.size() == static_cast<size_t>(best.K + 1)) {
            bool duplicate = false;
            for (const SeedSpec& seed : it->seeds) {
                duplicate =
                    duplicate || (seed.G == best.G && seed.K == best.K && seed.cuts == best.cuts);
            }
            if (!duplicate) {
                it->seeds.push_back(schedule_seed_spec(best));
            }
        }
    }
    if (work.empty()) {
        return results;
    }

    // Preserve baseline/neighbor layouts for every P before spending time on DP.
    vector<LayoutSeed> layouts;
    vector<BoundModel> models(work.size());
    vector<vector<array<i128, operation::kCount>>> durations(work.size());
    const auto stage_start = Clock::now();
    const auto total_budget = deadline - stage_start;
    const auto prep_deadline = stage_start + total_budget / 3;
    const auto dp_stage_deadline = stage_start + (total_budget * 2) / 3;
    size_t remaining_prep = work.size();
    for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
        --remaining_prep;
        const auto now = Clock::now();
        const auto remaining = max(Clock::duration::zero(), prep_deadline - now);
        const auto slice = remaining_prep == 0
                               ? remaining
                               : remaining / static_cast<Clock::duration::rep>(remaining_prep + 1);
        const auto p_prep_deadline = min(prep_deadline, now + slice);
        durations[p] = compute_durations(x, work[p].representative);
        if (!build_bound_model(x, work[p].representative, durations[p], models[p],
                               p_prep_deadline)) {
            continue;
        }
        for (const SeedSpec& seed : work[p].seeds) {
            if (seed.G > 0 && seed.G <= x.N * x.S / work[p].P &&
                valid_cuts(seed.cuts, x.L, seed.G, seed.K)) {
                seed_neighborhood(layouts, x, models[p], work[p].representative, seed.G, seed.K,
                                  seed.cuts, p_prep_deadline);
            }
        }
    }

    // Fairly divide the optimization window across distinct P values. The
    // contiguous DP is cheap; folded DP may stop between complete group counts.
    size_t remaining_placements = work.size();
    for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
        --remaining_placements;
        if (models[p].constraints.empty()) {
            continue;
        }
        const auto now = Clock::now();
        const auto available = max(Clock::duration::zero(), dp_stage_deadline - now);
        const auto slice =
            remaining_placements == 0
                ? available
                : available / static_cast<Clock::duration::rep>(remaining_placements + 1);
        const auto p_deadline = min(dp_stage_deadline, now + slice);
        const int max_contiguous = min(x.L, x.N * x.S / work[p].P);
        vector<LayoutSeed> p_layouts =
            contiguous_dp(x, work[p].representative, models[p], max_contiguous, p_deadline);
        layouts.insert(layouts.end(), make_move_iterator(p_layouts.begin()),
                       make_move_iterator(p_layouts.end()));
        if (expired(p_deadline)) {
            continue;
        }
        const int max_folded = min(x.L / 2, x.N * x.S / work[p].P);
        if (max_folded <= 0) {
            continue;
        }
        const auto segment = segment_costs(x, models[p], p_deadline);
        if (segment.empty()) {
            continue;
        }
        vector<LayoutSeed> folded =
            folded_dp(x, work[p].representative, models[p], max_folded, segment, p_deadline);
        layouts.insert(layouts.end(), make_move_iterator(folded.begin()),
                       make_move_iterator(folded.end()));
    }

    // Add cut interpolations only where the exact P/G/K forms match.
    const size_t original_layout_count = layouts.size();
    for (size_t i = 0; i < original_layout_count && !expired(deadline); ++i) {
        for (size_t j = 0; j < original_layout_count && !expired(deadline); ++j) {
            if (layouts[i].source == "placement_seed" &&
                layouts[j].source.rfind("threshold_dp_", 0) == 0 &&
                layouts[i].candidate.P == layouts[j].candidate.P && layouts[i].G == layouts[j].G &&
                layouts[i].K == layouts[j].K) {
                const auto p_it = find_if(work.begin(), work.end(), [&](const PlacementWork& item) {
                    return item.P == layouts[i].candidate.P;
                });
                if (p_it != work.end()) {
                    const size_t p = static_cast<size_t>(p_it - work.begin());
                    const LayoutSeed old_layout = layouts[i];
                    const LayoutSeed dp_layout = layouts[j];
                    interpolate_layouts(layouts, x, models[p], p_it->representative, old_layout,
                                        dp_layout, dp_stage_deadline);
                }
            }
        }
    }

    // Retain a small lower-bound-ranked set per P so one placement cannot use
    // the whole schedule-evaluation window.
    vector<LayoutSeed> selected;
    for (const PlacementWork& item : work) {
        vector<LayoutSeed> local;
        for (const LayoutSeed& layout : layouts) {
            if (layout.candidate.P == item.P) {
                local.push_back(layout);
            }
        }
        stable_sort(local.begin(), local.end(), [](const LayoutSeed& a, const LayoutSeed& b) {
            return a.lower_bound < b.lower_bound;
        });
        if (local.size() > kMaxLayoutsPerPlacement) {
            local.resize(kMaxLayoutsPerPlacement);
        }
        selected.insert(selected.end(), make_move_iterator(local.begin()),
                        make_move_iterator(local.end()));
    }

    // Round-robin through P values and evaluate complete static schedules.
    vector<vector<LayoutSeed>> by_placement(work.size());
    for (LayoutSeed& layout : selected) {
        for (size_t p = 0; p < work.size(); ++p) {
            if (layout.candidate.P == work[p].P) {
                by_placement[p].push_back(move(layout));
                break;
            }
        }
    }
    vector<size_t> at(work.size(), 0);
    bool progress = true;
    while (progress && !expired(deadline)) {
        progress = false;
        for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
            if (at[p] >= by_placement[p].size()) {
                continue;
            }
            progress = true;
            const LayoutSeed& layout = by_placement[p][at[p]++];
            ScheduleResult candidate;
            if (evaluate_layout(x, layout, durations[p], deadline, candidate)) {
                retain_result(results, move(candidate), best);
            }
        }
    }

    stable_sort(results.begin(), results.end(),
                [](const ScheduleResult& a, const ScheduleResult& b) { return a.time < b.time; });
    if (results.size() > kSeedLimit) {
        results.resize(kSeedLimit);
    }
    return results;
}

}  // namespace solver
