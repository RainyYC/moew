#pragma once
// Stable result and schedule serialization.
#include "../model/problem.hpp"
#include "../placement/expert_mapping.hpp"
#include "numeric.hpp"
namespace solver {
using namespace std;
void write_output(const InputData& x, const ScheduleResult& best, bool serial) {
    // This display table follows operation::Code index order.
    const array<string, operation::kCount> names = {
        "s", "disp", "gemm", "comb", "s_bwd", "comb_bwd", "gemm_dx", "gemm_dw", "disp_bwd", "s_dw"};
    cout << best.G << " " << best.c.P << "\nPSI\n" << best.K;
    for (int j = 1; j < best.K; j++) {
        cout << " " << best.cuts[j];
    }
    cout << "\nMAP\n";
    for (auto& r : best.c.map) {
        for (int e = 0; e < x.E; e++) {
            cout << (e ? " " : "") << r[e];
        }
        cout << "\n";
    }
    cout << "SCHEDULE\n";
    if (serial) {
        auto dur = compute_durations(x, best.c);
        i128 t = 0;
        auto emit = [&](int mb, int l, int op) {
            cout << to_decimal(t) << " " << mb << ":" << l << ":" << names[op] << "\n";
            t += dur[l][op] + 1;
        };
        for (int mb = 0; mb < x.mb; mb++) {
            for (int l = 0; l < x.L; l++) {
                emit(mb, l, operation::index(operation::kSharedForward));
                emit(mb, l, operation::index(operation::kDispatchForward));
                emit(mb, l, operation::index(operation::kExpertForward));
                emit(mb, l, operation::index(operation::kCombineForward));
            }
            for (int l = x.L - 1; l >= 0; l--) {
                emit(mb, l, operation::index(operation::kCombineBackward));
                emit(mb, l, operation::index(operation::kSharedBackward));
                emit(mb, l, operation::index(operation::kExpertInputGradient));
                emit(mb, l, operation::index(operation::kDispatchBackward));
                emit(mb, l, operation::index(operation::kExpertWeightGradient));
                emit(mb, l, operation::index(operation::kSharedWeightGradient));
            }
        }
    } else {
        for (auto& o : best.ops) {
            cout << to_decimal(o.start) << " " << o.mb << ":" << o.l << ":" << names[o.op] << "\n";
        }
    }
}

}  // namespace solver
