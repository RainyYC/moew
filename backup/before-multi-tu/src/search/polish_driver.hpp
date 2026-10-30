#pragma once
// Coordinate bounded local-polish passes and report their results.
#include "../search/local_engine_polish.hpp"
#include "limits.hpp"
#include "wave_search.hpp"
namespace solver {
using namespace std;
void polish_final_schedule(const InputData& x, ScheduleResult& best, bool serial, bool do_wave,
                           chrono::steady_clock::time_point main_start, int budget_ms,
                           const string& retime_mode, int polish_pass_limit) {
    if (!serial && do_wave && !best.ops.empty()) {
        auto dur = compute_durations(x, best.c);
        local_engine_polish::Stats total;
        total.exhausted = true;
        i128 resident = (x.E / best.c.P) * x.Z + x.Zs;
        auto prefix_deadline =
            main_start + chrono::milliseconds(search_limits::kPolishPrefixDeadlineMs);
        auto deadline = main_start + chrono::milliseconds(budget_ms);
        int prefix_rounds = 0;
        // Preserve the original small-instance search prefix and its per-round cap.
        if ((i128)x.mb * x.L * operation::kCount <= search_limits::kPrefixNodeLimit) {
            for (int round = 0; round < search_limits::kPrefixMaxRounds &&
                                chrono::steady_clock::now() +
                                        chrono::milliseconds(search_limits::kPrefixRoundReserveMs) <
                                    prefix_deadline;
                 round++) {
                vector<event_sched::Op> polished;
                i128 pol_time = best.time;
                local_engine_polish::Stats part;
                local_engine_polish::polish(
                    x.mb, x.L, best.G, best.group, dur, best.ops, x.M, x.U, x.Ua, resident,
                    polished, pol_time, part, prefix_deadline,
                    search_limits::kPrefixEvaluationsPerRound, 0, retime_mode == "auto");
                total.evaluated += part.evaluated;
                total.accepted += part.accepted;
                total.strict_improve += part.strict_improve;
                total.tie_moves += part.tie_moves;
                total.memory_fast_groups = part.memory_fast_groups;
                total.rounds++;
                prefix_rounds++;
                total.exhausted = total.exhausted && part.exhausted;
                if (part.accepted == 0) {
                    break;
                }
                if (pol_time < best.time) {
                    best.time = pol_time;
                }
                best.ops.swap(polished);
            }
        }
        int pass = 1;
        i128 anchor_time = best.time;
        auto extension_start = chrono::steady_clock::now();
        long long ext_evaluated = 0, ext_accepted = 0, ext_improved = 0;
        int ext_fast_groups = 0;
        while ((polish_pass_limit == 0 || pass <= polish_pass_limit) &&
               chrono::steady_clock::now() +
                       chrono::milliseconds(search_limits::kExtensionDeadlineReserveMs) <
                   deadline &&
               !(best.time == 0)) {
            vector<event_sched::Op> polished;
            i128 pol_time = best.time;
            local_engine_polish::Stats part;
            local_engine_polish::polish(x.mb, x.L, best.G, best.group, dur, best.ops, x.M, x.U,
                                        x.Ua, resident, polished, pol_time, part, deadline,
                                        search_limits::kExtensionIterationBudget, pass,
                                        retime_mode == "auto");
            ext_evaluated += part.evaluated;
            ext_accepted += part.accepted;
            ext_improved += part.strict_improve;
            ext_fast_groups = part.memory_fast_groups;
            if (part.accepted && pol_time <= best.time) {
                best.time = pol_time;
                best.ops.swap(polished);
            }
            // An entire pass with no legal improvement still changes the next pass seed.
            if (best.time == 0) {
                break;
            }
            pass++;
        }
        cerr << "LOCAL_ENGINE evaluated=" << total.evaluated << " accepted=" << total.accepted
             << " strict_improve=" << total.strict_improve << " tie_moves=" << total.tie_moves
             << " rounds=" << total.rounds << " prefix_rounds=" << prefix_rounds
             << " extension_passes=" << (pass - 1) << " extension_evaluated=" << ext_evaluated
             << " extension_accepted=" << ext_accepted << " extension_improved=" << ext_improved
             << " memory_fast_groups=" << ext_fast_groups
             << " anchor_Time=" << to_decimal(anchor_time) << " extension_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - extension_start).count()
             << " Time=" << to_decimal(best.time) << " exhausted=" << total.exhausted
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count() << "\n";
    }
}

}  // namespace solver
