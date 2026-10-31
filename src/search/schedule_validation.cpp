#include "schedule_validation.hpp"

#include "../core/operation_graph.hpp"
#include "../placement/expert_mapping.hpp"

namespace solver {
namespace {
using Interval = std::pair<i128, i128>;

int closed_interval_peak(std::vector<Interval> intervals) {
    std::sort(intervals.begin(), intervals.end());
    std::multiset<i128> active_ends;
    int peak = 0;
    std::size_t first = 0;
    while (first < intervals.size()) {
        std::size_t last = first;
        while (last < intervals.size() && intervals[last].first == intervals[first].first) {
            ++last;
        }
        while (!active_ends.empty() && *active_ends.begin() < intervals[first].first) {
            active_ends.erase(active_ends.begin());
        }
        peak = std::max(peak, static_cast<int>(active_ends.size() + last - first));
        for (std::size_t i = first; i < last; ++i) {
            if (intervals[i].second < intervals[i].first) {
                return std::numeric_limits<int>::max();
            }
            active_ends.insert(intervals[i].second);
        }
        first = last;
    }
    return peak;
}

bool is_communication_operation(int op) {
    return op == operation::kDispatchForward || op == operation::kCombineForward ||
           op == operation::kCombineBackward || op == operation::kDispatchBackward;
}
}  // namespace

bool is_feasible_schedule(const InputData& x, const ScheduleResult& result) {
    if (x.N <= 0 || x.S <= 0 || x.mb < 0 || x.L <= 0 || x.E <= 0 ||
        result.G <= 0 || result.K <= 0 ||
        result.c.P <= 0 || x.E % result.c.P != 0 ||
        static_cast<int>(result.c.map.size()) != x.L ||
        static_cast<int>(result.cuts.size()) != result.K + 1 ||
        static_cast<int>(result.group.size()) != x.L ||
        (result.K != result.G && result.K != 2 * result.G) ||
        result.G > x.L ||
        static_cast<i128>(result.G) * result.c.P > static_cast<i128>(x.N) * x.S ||
        (x.S % result.c.P != 0 && result.c.P % x.S != 0) ||
        result.cuts.front() != 0 || result.cuts.back() != x.L) {
        return false;
    }

    for (int layer = 0; layer < x.L; ++layer) {
        if (static_cast<int>(result.c.map[layer].size()) != x.E) {
            return false;
        }
        std::vector<int> expert_counts(result.c.P, 0);
        for (int rank : result.c.map[layer]) {
            if (rank < 0 || rank >= result.c.P) {
                return false;
            }
            ++expert_counts[rank];
        }
        for (int count : expert_counts) {
            if (count != x.E / result.c.P) {
                return false;
            }
        }
    }

    for (int block = 0; block < result.K; ++block) {
        if (result.cuts[block] < 0 || result.cuts[block] > x.L ||
            result.cuts[block + 1] < 0 || result.cuts[block + 1] > x.L ||
            result.cuts[block + 1] <= result.cuts[block]) {
            return false;
        }
    }

    std::vector<int> expected_group(x.L, -1);
    for (int block = 0; block < result.K; ++block) {
        const int group = result.K == result.G
                              ? block
                              : (block < result.G ? block : 2 * result.G - 1 - block);
        for (int layer = result.cuts[block]; layer < result.cuts[block + 1]; ++layer) {
            expected_group[layer] = group;
        }
    }
    if (result.group != expected_group) {
        return false;
    }

    const i128 node_count_128 = static_cast<i128>(x.mb) * x.L * operation::kCount;
    if (node_count_128 <= 0 || node_count_128 > std::numeric_limits<int>::max() ||
        result.ops.size() != static_cast<std::size_t>(node_count_128)) {
        return false;
    }
    const int node_count = static_cast<int>(node_count_128);
    const auto durations = compute_durations(x, result.c);
    std::vector<i128> starts(node_count, -1), ends(node_count, -1);
    std::vector<int> group_layers(result.G, 0);
    std::vector<std::array<std::vector<Interval>, operation::kEngineCount>> resources(result.G);
    i128 makespan = 0;
    i128 previous_serialized_start = -1;

    for (int group : result.group) {
        if (group < 0 || group >= result.G) {
            return false;
        }
        ++group_layers[group];
    }

    for (const auto& op : result.ops) {
        if (op.mb < 0 || op.mb >= x.mb || op.l < 0 || op.l >= x.L || op.op < 0 ||
            op.op >= operation::kCount || op.start < 0 ||
            op.start < previous_serialized_start) {
            return false;
        }
        previous_serialized_start = op.start;
        const int id = operation_graph::node_id(op.mb, op.l, op.op, x.L);
        if (starts[id] >= 0 || durations[op.l][op.op] < 0) {
            return false;
        }
        starts[id] = op.start;
        ends[id] = op.start + durations[op.l][op.op];
        makespan = std::max(makespan, ends[id]);
        const int engine = is_communication_operation(op.op)
                               ? operation::kCommunicationEngine
                               : operation::kComputeEngine;
        if (durations[op.l][op.op] > 0) {
            resources[result.group[op.l]][engine].push_back({starts[id], ends[id]});
        }
    }
    for (int id = 0; id < node_count; ++id) {
        if (starts[id] < 0) {
            return false;
        }
    }
    if (makespan != result.time) {
        return false;
    }

    auto id_of = [&x](int mb, int layer, int op) {
        return operation_graph::node_id(mb, layer, op, x.L);
    };
    bool dag_feasible = true;
    auto check_edge = [&](int from, int to) {
        dag_feasible = dag_feasible && ends[from] <= starts[to];
    };
    for (int mb = 0; mb < x.mb; ++mb) {
        for (int layer = 0; layer < x.L; ++layer) {
            operation_graph::append_layer_edges(mb, layer, x.L, id_of, check_edge);
        }
    }
    if (!dag_feasible) {
        return false;
    }

    for (int group = 0; group < result.G; ++group) {
        for (int engine = 0; engine < operation::kEngineCount; ++engine) {
            auto intervals = resources[group][engine];
            std::sort(intervals.begin(), intervals.end());
            i128 previous_end = -1;
            for (const auto& interval : intervals) {
                if (interval.first < previous_end) {
                    return false;
                }
                previous_end = std::max(previous_end, interval.second);
            }
        }
    }

    for (int group = 0; group < result.G; ++group) {
        std::vector<Interval> communication_intervals;
        std::vector<Interval> activation_intervals;
        bool has_positive_communication = false;
        for (int layer = 0; layer < x.L; ++layer) {
            if (result.group[layer] != group) {
                continue;
            }
            for (int mb = 0; mb < x.mb; ++mb) {
                const int base = operation_graph::node_id(mb, layer, 0, x.L);
                const i128 activation_start = ends[base + operation::kCombineForward];
                const i128 activation_end = starts[base + operation::kSharedBackward];
                if (activation_start > activation_end) {
                    return false;
                }
                activation_intervals.push_back({activation_start, activation_end});
                for (int op : operation::kCommunicationOperations) {
                    if (durations[layer][op] > 0) {
                        has_positive_communication = true;
                        communication_intervals.push_back(
                            {starts[base + op], ends[base + op]});
                    }
                }
            }
        }
        const int communication_peak = has_positive_communication
                                           ? closed_interval_peak(communication_intervals)
                                           : 0;
        const int activation_peak = closed_interval_peak(activation_intervals);
        if (communication_peak == std::numeric_limits<int>::max() ||
            activation_peak == std::numeric_limits<int>::max()) {
            return false;
        }
        const i128 resident = static_cast<i128>(group_layers[group]) *
                              (static_cast<i128>(x.E / result.c.P) * x.Z + x.Zs);
        const i128 memory_used = resident + x.U * communication_peak + x.Ua * activation_peak;
        if (memory_used > x.M) {
            return false;
        }
    }
    return true;
}
}  // namespace solver
