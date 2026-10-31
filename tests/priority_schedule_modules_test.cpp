#include "../src/placement/expert_mapping.hpp"
#include "../src/scheduling/list_scheduler.hpp"
#include "../src/scheduling/schedule_api.hpp"
#include "../src/search/priority_search.hpp"
#include "../src/search/schedule_validation.hpp"

#include <cassert>

int main() {
    using namespace solver;
    InputData x{};
    x.N = 2;
    x.S = 1;
    x.L = 2;
    x.E = 2;
    x.k = 1;
    x.mb = 2;
    x.M = 1000000000;
    x.Bi = 1;
    x.Bo = 1;
    x.Z = 1;
    x.Zs = 1;
    x.U = 3;
    x.Ua = 2;
    x.d = 1;
    x.b = 1;
    x.Fs = 1;
    x.Fio = 1;
    x.Fin = 1;
    x.ax = 1;
    x.bx = 1;
    x.T = {2, 2};
    x.load = {{1, 1}, {1, 1}};

    Candidate placement;
    placement.P = 1;
    placement.V = 1;
    placement.cuts = {0, 2};
    placement.map = {{0, 0}, {0, 0}};
    const auto durations = compute_durations(x, placement);
    const std::vector<int> layer_group = {0, 0};
    const std::vector<int> group_layers = {2};
    scheduling::ProblemView problem{x.mb, x.L, 1, layer_group, durations, group_layers};
    scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);

    for (scheduling::ListRankMode mode : {
             scheduling::ListRankMode::kRandomKey,
             scheduling::ListRankMode::kNonuniformMicrobatchOffsets}) {
        scheduling::ListConfig config;
        config.window = x.mb;
        config.fill_gaps = true;
        config.priority_mode = mode;
        config.random_seed = 17;
        config.random_jitter_span = 31;
        config.random_wave_stride = 4;
        config.pitch_numerator = 1;
        config.pitch_denominator = 4;
        config.duration_head = 1;
        config.microbatch_offset_ticks = {0, 47};
        config.microbatch_offset_denominator = 64;
        std::vector<event_sched::Op> operations;
        i128 time = 0;
        scheduling::ScheduleOutput output{operations, time};
        assert(scheduler.run(config, output));
        std::stable_sort(operations.begin(), operations.end(), [](const auto& left, const auto& right) {
            return std::tie(left.start, left.mb, left.l, left.op) <
                   std::tie(right.start, right.mb, right.l, right.op);
        });

        ScheduleResult result;
        result.c = placement;
        result.G = 1;
        result.K = 1;
        result.cuts = {0, 2};
        result.group = layer_group;
        result.ops = operations;
        result.time = time;
        assert(is_feasible_schedule(x, result));

        ScheduleResult duplicate = result;
        duplicate.ops.back() = duplicate.ops.front();
        assert(!is_feasible_schedule(x, duplicate));
        ScheduleResult unsorted = result;
        std::reverse(unsorted.ops.begin(), unsorted.ops.end());
        assert(!is_feasible_schedule(x, unsorted));
        ScheduleResult bad_cuts = result;
        bad_cuts.K = 2;
        bad_cuts.cuts = {0, 2, 2};
        assert(!is_feasible_schedule(x, bad_cuts));
    }

    scheduling::ListConfig pitch_config;
    pitch_config.window = x.mb;
    pitch_config.fill_gaps = true;
    pitch_config.priority_mode = scheduling::ListRankMode::kDagPitch;
    pitch_config.pitch_numerator = 1;
    pitch_config.pitch_denominator = 4;
    pitch_config.duration_head = 1;
    scheduling::ListConfig uniform_offset_config = pitch_config;
    uniform_offset_config.priority_mode =
        scheduling::ListRankMode::kNonuniformMicrobatchOffsets;
    uniform_offset_config.microbatch_offset_ticks = {0, 64};
    std::vector<event_sched::Op> pitch_ops;
    std::vector<event_sched::Op> offset_ops;
    i128 pitch_time = 0;
    i128 offset_time = 0;
    scheduling::ScheduleOutput pitch_output{pitch_ops, pitch_time};
    scheduling::ScheduleOutput offset_output{offset_ops, offset_time};
    assert(scheduler.run(pitch_config, pitch_output));
    assert(scheduler.run(uniform_offset_config, offset_output));
    const auto operation_order = [](const auto& left, const auto& right) {
        return std::tie(left.start, left.mb, left.l, left.op) <
               std::tie(right.start, right.mb, right.l, right.op);
    };
    std::stable_sort(pitch_ops.begin(), pitch_ops.end(), operation_order);
    std::stable_sort(offset_ops.begin(), offset_ops.end(), operation_order);
    assert(pitch_time == offset_time);
    assert(pitch_ops.size() == offset_ops.size());
    for (std::size_t index = 0; index < pitch_ops.size(); ++index) {
        assert(pitch_ops[index].start == offset_ops[index].start);
        assert(pitch_ops[index].mb == offset_ops[index].mb);
        assert(pitch_ops[index].l == offset_ops[index].l);
        assert(pitch_ops[index].op == offset_ops[index].op);
    }

    InputData no_memory = x;
    no_memory.M = 0;
    ScheduleResult valid;
    scheduling::ListConfig config;
    std::vector<event_sched::Op> operations;
    i128 time = 0;
    scheduling::ScheduleOutput output{operations, time};
    config.window = x.mb;
    assert(scheduler.run(config, output));
    std::stable_sort(operations.begin(), operations.end(), [](const auto& left, const auto& right) {
        return std::tie(left.start, left.mb, left.l, left.op) <
               std::tie(right.start, right.mb, right.l, right.op);
    });
    valid.c = placement;
    valid.G = 1;
    valid.K = 1;
    valid.cuts = {0, 2};
    valid.group = layer_group;
    valid.ops = operations;
    valid.time = time;
    assert(is_feasible_schedule(x, valid));
    ScheduleResult unsorted_seed = valid;
    std::reverse(unsorted_seed.ops.begin(), unsorted_seed.ops.end());
    assert(!is_feasible_schedule(x, unsorted_seed));
    ScheduleResult searched_best;
    searched_best.time = search_limits::kInfiniteTime;
    const std::vector<ScheduleResult> unsorted_seeds = {unsorted_seed};
    refine_priority_schedules(x, unsorted_seeds, searched_best,
                               std::chrono::steady_clock::now() +
                                   std::chrono::milliseconds(200));
    assert(!searched_best.ops.empty());
    assert(is_feasible_schedule(x, searched_best));

    InputData zero_memory_units = x;
    zero_memory_units.U = 0;
    zero_memory_units.Ua = 0;
    assert(is_feasible_schedule(zero_memory_units, valid));
    assert(!is_feasible_schedule(no_memory, valid));

    const auto sort_and_update_time = [&](ScheduleResult& candidate) {
        std::stable_sort(candidate.ops.begin(), candidate.ops.end(),
                         [](const auto& left, const auto& right) {
                             return std::tie(left.start, left.mb, left.l, left.op) <
                                    std::tie(right.start, right.mb, right.l, right.op);
                         });
        candidate.time = 0;
        for (const auto& op : candidate.ops) {
            candidate.time = std::max(candidate.time,
                                      op.start + durations[op.l][op.op]);
        }
    };

    ScheduleResult resource_overlap = valid;
    auto shared = std::find_if(resource_overlap.ops.begin(), resource_overlap.ops.end(),
                               [](const auto& op) {
                                   return op.mb == 0 && op.l == 0 &&
                                          op.op == operation::kSharedForward;
                               });
    auto expert = std::find_if(resource_overlap.ops.begin(), resource_overlap.ops.end(),
                               [](const auto& op) {
                                   return op.mb == 0 && op.l == 0 &&
                                          op.op == operation::kExpertForward;
                               });
    assert(shared != resource_overlap.ops.end() && expert != resource_overlap.ops.end());
    expert->start = shared->start;
    sort_and_update_time(resource_overlap);
    assert(!is_feasible_schedule(x, resource_overlap));

    ScheduleResult bad_dependency = valid;
    auto dispatch = std::find_if(bad_dependency.ops.begin(), bad_dependency.ops.end(),
                                 [](const auto& op) {
                                     return op.mb == 0 && op.l == 0 &&
                                            op.op == operation::kDispatchForward;
                                 });
    expert = std::find_if(bad_dependency.ops.begin(), bad_dependency.ops.end(),
                          [](const auto& op) {
                              return op.mb == 0 && op.l == 0 &&
                                     op.op == operation::kExpertForward;
                          });
    assert(dispatch != bad_dependency.ops.end() && expert != bad_dependency.ops.end());
    dispatch->start = expert->start + durations[0][operation::kExpertForward] + 1;
    sort_and_update_time(bad_dependency);
    assert(!is_feasible_schedule(x, bad_dependency));

    ScheduleResult bad_grid = valid;
    bad_grid.c.P = 2;
    bad_grid.c.map = {{0, 1}, {0, 1}};
    bad_grid.G = 2;
    bad_grid.K = 2;
    bad_grid.cuts = {0, 1, 2};
    bad_grid.group = {0, 1};
    assert(!is_feasible_schedule(x, bad_grid));

    InputData incompatible_grid = x;
    incompatible_grid.N = 1;
    incompatible_grid.S = 3;
    ScheduleResult bad_p_s = valid;
    bad_p_s.c.P = 2;
    bad_p_s.c.map = {{0, 1}, {0, 1}};
    assert(!is_feasible_schedule(incompatible_grid, bad_p_s));
    return 0;
}
