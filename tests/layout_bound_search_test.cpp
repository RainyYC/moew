// Standalone exhaustive checks for the internal layout-bound DPs.
#include "../src/search/layout_bound_search.cpp"

#include <cassert>
#include <iostream>

using namespace solver;
using namespace std;

int main() {
    InputData x{};
    x.L = 8;
    x.mb = 3;
    x.N = 8;
    x.S = 1;
    x.E = 1;
    x.M = 100000;
    Candidate c;
    c.P = 1;
    c.V = 1;
    c.cuts = {0, x.L};
    BoundModel model;
    model.resident_per_layer = 1;
    const vector<vector<int>> weights{
        {4, 1, 8, 2, 6, 3, 7, 5}, {2, 9, 1, 7, 3, 8, 4, 6}, {5, 3, 4, 8, 1, 7, 2, 9}};
    for (int k = 0; k < static_cast<int>(weights.size()); ++k) {
        ResourceConstraint q;
        q.release = k % 2;
        q.tail = (k + 1) % 3;
        q.engine = k % 2;
        q.prefix.assign(x.L + 1, 0);
        for (int i = 0; i < x.L; ++i) {
            q.prefix[i + 1] = q.prefix[i] + weights[k][i];
        }
        model.constraints.push_back(move(q));
    }

    auto enumerate_cuts = [&](int K, auto&& visit) {
        vector<int> cuts{0};
        auto rec = [&](auto&& self, int next, int remaining) -> void {
            if (remaining == 1) {
                if (x.L - next >= 1) {
                    cuts.push_back(x.L);
                    visit(cuts);
                    cuts.pop_back();
                }
                return;
            }
            const int last = x.L - remaining + 1;
            for (int end = next + 1; end <= last; ++end) {
                cuts.push_back(end);
                self(self, end, remaining - 1);
                cuts.pop_back();
            }
        };
        rec(rec, 0, K);
    };

    const auto deadline = chrono::steady_clock::now() + chrono::seconds(10);
    auto straight = contiguous_dp(x, c, model, x.L, deadline);
    for (int G = 1; G <= x.L; ++G) {
        i128 brute = kInf;
        enumerate_cuts(G, [&](const vector<int>& cuts) {
            brute = min(brute, layout_bound(x, model, cuts, G));
        });
        auto it = find_if(straight.begin(), straight.end(),
                          [&](const LayoutSeed& s) { return s.G == G && s.K == G; });
        assert(it != straight.end() && it->lower_bound == brute);
    }

    auto segment = segment_costs(x, model, deadline);
    auto folded = folded_dp(x, c, model, x.L / 2, segment, deadline);
    for (int G = 1; G <= x.L / 2; ++G) {
        i128 brute = kInf;
        enumerate_cuts(2 * G, [&](const vector<int>& cuts) {
            brute = min(brute, layout_bound(x, model, cuts, G));
        });
        auto it = find_if(folded.begin(), folded.end(),
                          [&](const LayoutSeed& s) { return s.G == G && s.K == 2 * G; });
        assert(it != folded.end() && it->lower_bound == brute);
    }

    set<size_t> ranks;
    for (int j = 3; j <= 12; ++j) {
        for (int b = 2; b < j; ++b) {
            for (int a = 1; a < b; ++a) {
                for (int i = 0; i < a; ++i) {
                    assert(ranks.insert(colex_rank(i, a, b, j)).second);
                }
            }
        }
    }
    assert(ranks.size() == choose4(13));

    vector<int> cuts{0, 2, 4, 6, 8, 10, 12};
    auto moved = cuts;
    moved[1] += 1;
    moved[5] += 1;
    const auto before_group = make_group_map(cuts, 3, 12);
    const auto after_group = make_group_map(moved, 3, 12);
    assert(valid_cuts(moved, 12, 3, 6));
    assert(count_layers(before_group, 3) == count_layers(after_group, 3));

    InputData x_seed{};
    x_seed.L = 12;
    x_seed.N = 3;
    x_seed.S = 1;
    x_seed.M = 100000;
    x_seed.mb = 1;
    BoundModel seed_model;
    seed_model.resident_per_layer = 1;
    ResourceConstraint seed_constraint;
    seed_constraint.prefix.assign(x_seed.L + 1, 0);
    for (int l = 0; l < x_seed.L; ++l) {
        seed_constraint.prefix[l + 1] = seed_constraint.prefix[l] + (l % 4) + 1;
    }
    seed_model.constraints.push_back(seed_constraint);
    Candidate stale_candidate;
    stale_candidate.P = 1;
    stale_candidate.V = 1;
    stale_candidate.cuts = {0, 12};
    ScheduleResult current;
    current.c = stale_candidate;
    current.G = 3;
    current.K = 6;
    current.cuts = {0, 2, 4, 6, 8, 10, 12};
    const SeedSpec actual_seed = schedule_seed_spec(current);
    assert(actual_seed.G == 3 && actual_seed.K == 6 && actual_seed.cuts == current.cuts);
    assert(actual_seed.cuts != current.c.cuts);
    assert(actual_seed.G <= x_seed.N * x_seed.S / current.c.P);
    vector<LayoutSeed> moves;
    seed_neighborhood(moves, x_seed, seed_model, current.c, actual_seed.G, actual_seed.K,
                      actual_seed.cuts);
    const auto mirror = find_if(moves.begin(), moves.end(), [](const LayoutSeed& seed) {
        return seed.source == "mirror_pair_shift";
    });
    assert(mirror != moves.end());
    assert(any_of(moves.begin(), moves.end(),
                  [](const LayoutSeed& seed) { return seed.source == "mirror_two_pair_shift"; }));
    assert(any_of(moves.begin(), moves.end(),
                  [](const LayoutSeed& seed) { return seed.source == "folded_single_cut_shift"; }));
    assert(count_layers(make_group_map(mirror->cuts, 3, 12), 3) ==
           count_layers(make_group_map(actual_seed.cuts, 3, 12), 3));
    LayoutSeed dp_seed{current.c, 3, 6, {0, 5, 7, 8, 10, 11, 12}, 0, "threshold_dp_folded"};
    const size_t before_interpolation = moves.size();
    interpolate_layouts(moves, x_seed, seed_model, current.c, moves.front(), dp_seed);
    assert(moves.size() > before_interpolation);
    assert(any_of(moves.begin(), moves.end(),
                  [](const LayoutSeed& seed) { return seed.source == "seed_dp_interpolation"; }));
    assert(any_of(moves.begin(), moves.end(), [](const LayoutSeed& seed) {
        return seed.cuts == vector<int>({0, 3, 5, 6, 8, 10, 12});
    }));
    BoundModel zero_resident = seed_model;
    zero_resident.resident_per_layer = 0;
    assert(layout_bound(x_seed, zero_resident, actual_seed.cuts, actual_seed.G) < kInf);
    InputData large_index = x_seed;
    large_index.L = 200;
    vector<vector<i128>> small_segment(large_index.L + 1, vector<i128>(large_index.L + 1, 0));
    assert(folded_dp(large_index, current.c, seed_model, 2, small_segment, deadline).empty());
    const size_t before_invalid_group = moves.size();
    add_layout(moves, x_seed, seed_model, current.c, 4, {0, 3, 6, 9, 12}, "invalid_G");
    assert(moves.size() == before_invalid_group);
    cout << "layout bound DP exhaustive checks passed\n";
}
