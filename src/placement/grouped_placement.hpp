#pragma once
#include "../common.hpp"

// ===== grouped_placement =====

// Bounded exact placement search for layers with only a few distinct slot
// weights. Experts with equal weights are grouped; the search assigns counts
// of each weight to ranks, then materialize() maps those counts back to the
// original expert indices.

namespace grouped_placement {
using i128 = __int128_t;
namespace limits {
inline constexpr int kMaxWeightTypes = 4;
inline constexpr int kMaxRanks = 32;
inline constexpr int kMaxSlotsPerRank = 32;
inline constexpr std::uint64_t kDefaultNodeBudget = 250000;
}  // namespace limits

struct Plan {
    std::vector<i128> values;                   // sorted distinct slot weights
    std::vector<std::vector<int>> rank_counts;  // [rank][weight type]
    i128 peak = 0;
};

namespace detail {
struct State {
    int rank;
    int first_pattern;
    std::vector<int> used;

    bool operator==(const State& other) const {
        return rank == other.rank && first_pattern == other.first_pattern && used == other.used;
    }
};

struct StateHash {
    std::size_t operator()(const State& state) const {
        std::size_t h = std::hash<int>{}(state.rank);
        auto mix = [&h](std::size_t x) { h ^= x + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2); };
        mix(std::hash<int>{}(state.first_pattern));
        for (int x : state.used) {
            mix(std::hash<int>{}(x));
        }
        return h;
    }
};

class Search {
private:
    int P;
    int per_rank;
    i128 target;
    const std::vector<i128>& values;
    const std::vector<int>& available;
    std::uint64_t budget;
    std::uint64_t visited = 0;
    bool exhausted = false;
    std::vector<std::vector<int>> patterns;
    std::vector<std::vector<int>> solution;
    std::unordered_set<State, StateHash> failed;

public:
    Search(int p, int q, i128 cap, const std::vector<i128>& type_values,
           const std::vector<int>& type_counts, std::uint64_t node_budget)
        : P(p),
          per_rank(q),
          target(cap),
          values(type_values),
          available(type_counts),
          budget(node_budget) {}

    bool solve() {
        std::vector<int> pattern(values.size(), 0);
        enumerate_patterns(0, per_rank, 0, pattern);
        if (exhausted || patterns.empty()) {
            return false;
        }
        std::vector<int> used(values.size(), 0);
        std::vector<std::vector<int>> chosen;
        chosen.reserve(P);
        return dfs(0, 0, used, chosen) && !exhausted;
    }

    bool is_exhausted() const {
        return exhausted;
    }

    std::vector<std::vector<int>> take_solution() {
        return std::move(solution);
    }

private:
    bool tick() {
        if (++visited > budget) {
            exhausted = true;
            return false;
        }
        return true;
    }

    void enumerate_patterns(int type, int slots_left, i128 load, std::vector<int>& counts) {
        if (exhausted || !tick()) {
            return;
        }
        if (type == static_cast<int>(values.size()) - 1) {
            int n = slots_left;
            if (n < 0 || n > available[type]) {
                return;
            }
            i128 sum = load + static_cast<i128>(n) * values[type];
            if (sum > target) {
                return;
            }
            counts[type] = n;
            patterns.push_back(counts);
            return;
        }
        const int max_n = std::min(slots_left, available[type]);
        for (int n = 0; n <= max_n && !exhausted; ++n) {
            i128 next_load = load + static_cast<i128>(n) * values[type];
            if (next_load > target) {
                break;
            }
            counts[type] = n;
            enumerate_patterns(type + 1, slots_left - n, next_load, counts);
        }
    }

    bool dfs(int rank, int first_pattern, std::vector<int>& used,
             std::vector<std::vector<int>>& chosen) {
        if (!tick()) {
            return false;
        }
        if (rank == P) {
            if (used == available) {
                solution = chosen;
                return true;
            }
            return false;
        }

        State key{rank, first_pattern, used};
        if (failed.find(key) != failed.end()) {
            return false;
        }
        const int remaining_ranks = P - rank - 1;
        for (int p = first_pattern; p < static_cast<int>(patterns.size()); ++p) {
            const auto& pattern = patterns[p];
            bool fits = true;
            for (std::size_t t = 0; t < used.size(); ++t) {
                if (used[t] + pattern[t] > available[t]) {
                    fits = false;
                    break;
                }
                // After this rank, remaining experts of this type must still
                // fit in the remaining rank capacities.
                if (available[t] - used[t] - pattern[t] > remaining_ranks * per_rank) {
                    fits = false;
                    break;
                }
            }
            if (!fits) {
                continue;
            }
            for (std::size_t t = 0; t < used.size(); ++t) {
                used[t] += pattern[t];
            }
            chosen.push_back(pattern);
            if (dfs(rank + 1, p, used, chosen)) {
                return true;
            }
            chosen.pop_back();
            for (std::size_t t = 0; t < used.size(); ++t) {
                used[t] -= pattern[t];
            }
            if (exhausted) {
                return false;
            }
        }
        failed.insert(std::move(key));
        return false;
    }
};
}  // namespace detail

// Find a rank-by-weight allocation under target_peak. Returns false when the
// target is infeasible, the type count is outside the supported small range,
// or the bounded search exhausts its node budget. It never mutates input.
// Search is bounded to <=4 weight types, P<=32, per_rank<=32 and the supplied
// node budget. For other shapes, retain the caller's existing MAP.
inline bool find_at_peak(const std::vector<i128>& slots, int P, int per_rank, i128 target_peak,
                         Plan& out, std::uint64_t node_budget = limits::kDefaultNodeBudget) {
    if (P < 1 || P > limits::kMaxRanks || per_rank < 1 || per_rank > limits::kMaxSlotsPerRank ||
        slots.size() != static_cast<std::size_t>(P) * per_rank || target_peak < 0 ||
        node_budget == 0) {
        return false;
    }

    std::vector<i128> values = slots;
    if (std::any_of(values.begin(), values.end(), [](i128 x) { return x < 0; })) {
        return false;
    }
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
    if (values.empty() || values.size() > limits::kMaxWeightTypes) {
        return false;
    }

    std::vector<int> available(values.size(), 0);
    for (i128 x : slots) {
        int t =
            static_cast<int>(std::lower_bound(values.begin(), values.end(), x) - values.begin());
        ++available[t];
    }

    detail::Search search(P, per_rank, target_peak, values, available, node_budget);
    if (!search.solve()) {
        return false;
    }

    Plan result;
    result.values = std::move(values);
    result.rank_counts = search.take_solution();
    result.peak = target_peak;
    out = std::move(result);
    return true;
}

// Convert a cached type-count plan back to expert-index ranks for this layer.
// This explicitly re-buckets the current slots, so plans can safely be reused
// across layers with the same value histogram but different expert ordering.
inline bool materialize(const std::vector<i128>& slots, const Plan& plan, std::vector<int>& row) {
    const int P = static_cast<int>(plan.rank_counts.size());
    if (P < 1 || plan.values.empty() || plan.values.size() > limits::kMaxWeightTypes) {
        return false;
    }
    const std::size_t K = plan.values.size();
    std::vector<std::vector<int>> experts(K);
    for (int e = 0; e < static_cast<int>(slots.size()); ++e) {
        auto it = std::lower_bound(plan.values.begin(), plan.values.end(), slots[e]);
        if (it == plan.values.end() || *it != slots[e]) {
            return false;
        }
        experts[static_cast<std::size_t>(it - plan.values.begin())].push_back(e);
    }
    std::vector<int> expected(K, 0);
    for (const auto& rank : plan.rank_counts) {
        if (rank.size() != K) {
            return false;
        }
        for (std::size_t t = 0; t < K; ++t) {
            if (rank[t] < 0) {
                return false;
            }
            expected[t] += rank[t];
        }
    }
    for (std::size_t t = 0; t < K; ++t) {
        if (expected[t] != static_cast<int>(experts[t].size())) {
            return false;
        }
    }

    std::vector<int> result(slots.size(), -1);
    std::vector<std::size_t> cursor(K, 0);
    for (int r = 0; r < P; ++r) {
        int rank_size = 0;
        for (std::size_t t = 0; t < K; ++t) {
            rank_size += plan.rank_counts[r][t];
            for (int n = 0; n < plan.rank_counts[r][t]; ++n) {
                if (cursor[t] >= experts[t].size()) {
                    return false;
                }
                result[experts[t][cursor[t]++]] = r;
            }
        }
        if (rank_size != static_cast<int>(slots.size() / P)) {
            return false;
        }
    }
    if (std::any_of(result.begin(), result.end(), [](int r) { return r < 0; })) {
        return false;
    }
    row = std::move(result);
    return true;
}

}  // namespace grouped_placement
