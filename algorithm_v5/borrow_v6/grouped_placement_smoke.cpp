#include "../grouped_placement.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <numeric>
#include <vector>

using grouped_placement::i128;

static i128 peak_of(const std::vector<i128>& slots, int P,
                    const std::vector<int>& row) {
    std::vector<i128> loads(P, 0);
    for (std::size_t e = 0; e < slots.size(); ++e) loads[row[e]] += slots[e];
    return *std::max_element(loads.begin(), loads.end());
}

static bool valid_capacities(const std::vector<i128>& slots, int P,
                             const std::vector<int>& row, int per_rank) {
    if (row.size() != slots.size()) return false;
    std::vector<int> counts(P, 0);
    for (int r : row) {
        if (r < 0 || r >= P) return false;
        ++counts[r];
    }
    return std::all_of(counts.begin(), counts.end(),
                       [per_rank](int n) { return n == per_rank; });
}

int main() {
    constexpr int P = 16;
    constexpr int per_rank = 16;
    std::vector<i128> slots;
    slots.insert(slots.end(), 168, 2);
    slots.insert(slots.end(), 72, 34);
    slots.insert(slots.end(), 16, 50);

    // Baseline m=240 is the measured final MAP for r256_v8_c8a.
    constexpr int baseline_peak = 240;
    grouped_placement::Plan plan;
    assert(grouped_placement::find_at_peak(slots, P, per_rank, 224, plan));
    std::vector<int> row;
    assert(grouped_placement::materialize(slots, plan, row));
    assert(valid_capacities(slots, P, row, per_rank));
    assert(peak_of(slots, P, row) == 224);
    assert(peak_of(slots, P, row) < baseline_peak);
    grouped_placement::Plan below_average;
    assert(!grouped_placement::find_at_peak(slots, P, per_rank, 223, below_average));

    // Reuse the type-count plan with a different expert ordering. Materialized
    // expert indices must still have the exact same per-rank capacity and peak.
    std::rotate(slots.begin(), slots.begin() + 73, slots.end());
    std::reverse(slots.begin(), slots.end());
    std::vector<int> reordered_row;
    assert(grouped_placement::materialize(slots, plan, reordered_row));
    assert(valid_capacities(slots, P, reordered_row, per_rank));
    assert(peak_of(slots, P, reordered_row) == 224);

    std::cout << "grouped placement smoke passed: baseline m=240, candidate m=224, "
                 "P=16, per_rank=16; cached type plan remapped after permutation\n";
}
