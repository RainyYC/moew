#include "event_scheduler.hpp"
#include "../common.hpp"
#include "../core/operation_graph.hpp"
#include "../model/scheduled_operation.hpp"

// ===== event_scheduler =====

// Event driven scheduler for the ten-operation microbatch/layer DAG.
// Times and all time arithmetic remain signed 128-bit integers.

namespace event_sched {
// Operation codes follow operation::Code in common.hpp.
// activation_capacity[g] is the number of simultaneously reserved activation
// slots A_g after reserving communication buffers. comm_buffers[g] is between
// zero and operation::kMaxCommunicationBuffers. Zero is allowed only when every communication
// duration on that group is zero; the official checker then skips communication-buffer accounting.
// Modes 0/1/2 are the existing policies. Mode 3 uses a global bottom-level
// key and optionally adds a forward-fill bonus to ops 0..3 for mb<fill_mbs and
// group<fill_groups. reward_tenths is in tenths of the one-microbatch bottleneck
// workload (e.g. 5=0.5x, 10=1x, 100=10x). flat_reward selects a flat bonus;
// otherwise the bonus ramps down by (fs-g)/fs * (fm-mb)/fm. A zero reward gives
// the no-fill bottom-level baseline for mode 3.
// window==0 means no extra microbatch window limit.
namespace detail {
struct Node {
    int mb, l, op, indeg = 0;
};
struct Event {
    i128 t;
    int kind;  // event_sched::limits::kEventCompletion / kReservationReturn
    int node, group;
};
struct EventLater {
    bool operator()(const Event& a, const Event& b) const {
        if (a.t != b.t) {
            return a.t > b.t;
        }
        if (a.kind != b.kind) {
            return a.kind > b.kind;
        }
        if (a.node != b.node) {
            return a.node > b.node;
        }
        return a.group > b.group;
    }
};
struct ReadyItem {
    int node, mode, p0, p1, p2, p3;
    i128 tail;
};
struct ReadyLater {
    bool operator()(const ReadyItem& a, const ReadyItem& b) const {
        if (a.p0 != b.p0) {
            return a.p0 > b.p0;
        }
        if (a.mode && a.tail != b.tail) {
            return a.tail < b.tail;
        }
        return std::tie(a.p1, a.p2, a.p3, a.node) > std::tie(b.p1, b.p2, b.p3, b.node);
    }
};

inline int engine(int op) {
    return (op == operation::kDispatchForward || op == operation::kCombineForward ||
            op == operation::kCombineBackward || op == operation::kDispatchBackward)
               ? operation::kCommunicationEngine
               : operation::kComputeEngine;
}

inline ReadyItem priority_item(const Node& n, int id, int mode, i128 tail) {
    int p = 0;
    switch (n.op) {
        // Input-gradient/reverse work first. s_bwd releases a conservative
        // activation reservation one time unit after it starts.
        case operation::kSharedBackward:
            p = 0;
            break;
        case operation::kExpertInputGradient:
            p = 1;
            break;
        case operation::kDispatchBackward:
            p = 2;
            break;
        case operation::kCombineBackward:
            p = 3;
            break;
        // Continue an established forward wave before opening layer zero of a
        // new microbatch. Within a layer, ready joins / later forward steps win.
        case operation::kSharedForward:
        case operation::kDispatchForward:
            p = (n.l == 0 ? 5 : 4);
            break;
        case operation::kExpertForward:
            p = 4;
            break;
        case operation::kCombineForward:
            p = 4;
            break;
        // Weight gradients fill otherwise idle compute slots.
        case operation::kExpertWeightGradient:
        case operation::kSharedWeightGradient:
            p = 6;
            break;
    }
    int layer_order =
        (n.op == operation::kSharedBackward || n.op == operation::kCombineBackward ||
         n.op == operation::kExpertInputGradient || n.op == operation::kDispatchBackward)
            ? -n.l
            : n.l;
    if (mode == 1) {
        // Mode B: mild reverse-work bias, then exact longest remaining path.
        int reverse =
            (n.op == operation::kSharedBackward || n.op == operation::kCombineBackward ||
             n.op == operation::kExpertInputGradient || n.op == operation::kDispatchBackward)
                ? 0
                : ((n.op == operation::kExpertWeightGradient ||
                    n.op == operation::kSharedWeightGradient)
                       ? 2
                       : 1);
        return ReadyItem{id, 1, reverse, n.mb, layer_order, n.op, tail};
    }
    if (mode == 2) {
        int coarse;
        if (engine(n.op) == operation::kCommunicationEngine) {
            coarse = (n.op == operation::kCombineForward || n.op == operation::kDispatchBackward)
                         ? 0
                         : 1;
        } else if (n.op == operation::kSharedForward || n.op == operation::kExpertForward ||
                   n.op == operation::kSharedBackward || n.op == operation::kExpertInputGradient) {
            coarse = 0;
        } else if (n.op == operation::kCombineBackward) {
            coarse = 1;
        } else if (n.op == operation::kExpertWeightGradient ||
                   n.op == operation::kSharedWeightGradient) {
            coarse = 3;
        } else {
            coarse = 2;
        }
        return ReadyItem{id, 2, coarse, n.mb, layer_order, n.op, tail};
    }
    if (mode == 3) {
        // Fill-boost mode uses one cross-engine, time-dimensional key; its
        // forward bonus is already included in `tail` by make_ready().
        return ReadyItem{id, 3, 0, n.mb, layer_order, n.op, tail};
    }
    return ReadyItem{id, 0, p, n.mb, layer_order, n.op, 0};
}
}  // namespace detail

// Schedule all operation::kCount*mb*L operations. `layer_group` has L entries;
// `dur[l][op]` are nonnegative compute_durations. `group_layers[g]` is n_g.
// Returns false only for malformed/impossible inputs or a deadlocked state.
bool schedule(int mb, int L, int G, const std::vector<int>& layer_group,
                     const std::vector<std::array<i128, operation::kCount>>& dur,
                     const std::vector<int>& group_layers,
                     const std::vector<int>& activation_capacity,
                     const std::vector<int>& comm_buffers, int window, std::vector<Op>& out,
                     i128& makespan, int mode, int fill_groups, int fill_mbs,
                     int reward_tenths, bool flat_reward, int window_release) {
    using namespace detail;
    out.clear();
    makespan = 0;
    if (mb < 0 || L <= 0 || G <= 0 || (int)layer_group.size() != L || (int)dur.size() != L ||
        (int)group_layers.size() != G || (int)activation_capacity.size() != G ||
        (int)comm_buffers.size() != G) {
        return false;
    }
    i128 total_nodes = (i128)mb * L * operation::kCount;
    if (total_nodes > 2147483647) {
        return false;
    }
    int N = (int)total_nodes;
    for (int g = 0; g < G; ++g) {
        if (group_layers[g] < 0 || activation_capacity[g] < group_layers[g] ||
            (comm_buffers[g] < 0 || comm_buffers[g] > operation::kMaxCommunicationBuffers)) {
            return false;
        }
    }
    std::vector<int> actual(G, 0);
    for (int l = 0; l < L; ++l) {
        if (layer_group[l] < 0 || layer_group[l] >= G) {
            return false;
        }
        ++actual[layer_group[l]];
        for (int o = 0; o < operation::kCount; ++o) {
            if (dur[l][o] < 0) {
                return false;
            }
        }
    }
    if (actual != group_layers) {
        return false;
    }
    for (int g = 0; g < G; ++g) {
        if (comm_buffers[g] == 0) {
            for (int l = 0; l < L; ++l) {
                if (layer_group[l] == g) {
                    if (dur[l][operation::kDispatchForward] != 0 ||
                        dur[l][operation::kCombineForward] != 0 ||
                        dur[l][operation::kCombineBackward] != 0 ||
                        dur[l][operation::kDispatchBackward] != 0) {
                        return false;
                    }
                }
            }
        }
    }

    std::vector<Node> nodes(N);
    auto idof = [L](int m, int l, int o) { return operation_graph::node_id(m, l, o, L); };
    std::vector<std::vector<int>> out_edges(N);
    auto edge = [&](int a, int b) {
        out_edges[a].push_back(b);
        ++nodes[b].indeg;
    };
    for (int m = 0; m < mb; ++m) {
        for (int l = 0; l < L; ++l) {
            for (int o = 0; o < operation::kCount; ++o) {
                nodes[idof(m, l, o)] = Node{m, l, o, 0};
            }
        }
    }
    for (int m = 0; m < mb; ++m) {
        for (int l = 0; l < L; ++l) {
            operation_graph::append_layer_edges(m, l, L, idof, edge);
        }
    }

    // Bottom-level is identical for every microbatch because compute_durations and DAG
    // structure are identical. Compute it once on mb=0, then reuse it.
    if (mode != 0 && mode != 1 && mode != 2 && mode != 3) {
        return false;
    }
    if (mode == 3 && (fill_groups < 0 || fill_groups > G || fill_mbs < 0 || fill_mbs > mb ||
                      reward_tenths < 0 || reward_tenths > 100)) {
        return false;
    }
    if (window_release < 0 || window_release > 1) {
        return false;
    }
    std::vector<i128> bottom(N, 0);
    if ((mode == 1 || mode == 2 || mode == 3) && mb > 0) {
        std::vector<char> seen(L * operation::kCount, 0);
        std::function<i128(int)> calc = [&](int id) -> i128 {
            int local = id % (L * operation::kCount);
            if (seen[local]) {
                return bottom[id];
            }
            seen[local] = 1;
            i128 child = 0;
            for (int v : out_edges[id]) {
                child = std::max(child, calc(v));
            }
            bottom[id] = dur[nodes[id].l][nodes[id].op] + child;
            return bottom[id];
        };
        for (int id = 0; id < L * operation::kCount; ++id) {
            calc(id);
        }
        for (int m = 1; m < mb; ++m) {
            for (int local = 0; local < L * operation::kCount; ++local) {
                bottom[m * L * operation::kCount + local] = bottom[local];
            }
        }
    }
    std::vector<std::vector<i128>> fwd_bonus;
    if (mode == 3 && reward_tenths > 0 && fill_groups > 0 && fill_mbs > 0) {
        fwd_bonus.assign(G, std::vector<i128>(mb, 0));
        std::vector<i128> comp_work(G, 0), comm_work(G, 0);
        for (int l = 0; l < L; ++l) {
            int g = layer_group[l];
            for (int o = 0; o < operation::kCount; ++o) {
                (engine(o) == operation::kComputeEngine ? comp_work[g] : comm_work[g]) += dur[l][o];
            }
        }
        i128 B = 0;
        for (int g = 0; g < G; ++g) {
            B = std::max(B, std::max(comp_work[g], comm_work[g]));
        }
        for (int g = 0; g < fill_groups; ++g) {
            for (int m = 0; m < fill_mbs; ++m) {
                i128 numerator = B * reward_tenths;
                i128 denominator = 10;
                if (!flat_reward) {
                    numerator *= (fill_groups - g);
                    numerator *= (fill_mbs - m);
                    denominator *= fill_groups;
                    denominator *= fill_mbs;
                }
                fwd_bonus[g][m] = numerator / denominator;
            }
        }
    }

    std::vector<std::priority_queue<ReadyItem, std::vector<ReadyItem>, ReadyLater>> ready(
        operation::kEngineCount * G);
    std::vector<int> remaining(G), admitted(G, 0);
    // `remaining[g]` counts available reservation slots, not live activations.
    for (int g = 0; g < G; ++g) {
        remaining[g] = activation_capacity[g];
    }
    std::vector<int> done_mb(mb, 0);
    std::vector<std::vector<int>> done_sbwd;
    std::vector<char> window_released;
    int windows_in_use = 0;
    if (window_release == 1) {
        done_sbwd.assign(G, std::vector<int>(mb, 0));
        window_released.assign(mb, 0);
    }
    std::vector<char> mb_active(mb, 0), busy(operation::kEngineCount * G, 0);
    std::vector<i128> last_comm_start(G, 0), last_comm_end(G, 0);
    std::vector<char> has_comm(G, 0);
    std::priority_queue<Event, std::vector<Event>, EventLater> events;
    int next_mb = 0, active_mb = 0, finished = 0;
    const int W = window > 0 ? window : mb;

    auto make_ready = [&](int id) {
        const Node& n = nodes[id];
        int g = layer_group[n.l];
        i128 urgency = bottom[id];
        if (mode == 3 && n.op <= operation::kCombineForward && g < fill_groups && n.mb < fill_mbs &&
            reward_tenths > 0) {
            urgency += fwd_bonus[g][n.mb];
        }
        ready[operation::kEngineCount * g + engine(n.op)].push(priority_item(n, id, mode, urgency));
    };
    std::vector<char> node_done(N, 0);
    auto take_ready = [&](int slot, i128 now) -> int {
        auto& q = ready[slot];
        if (mode != 2) {
            int id = q.top().node;
            q.pop();
            return id;
        }
        std::vector<ReadyItem> candidates, deferred;
        candidates.reserve(16);
        deferred.reserve(16);
        for (int k = 0; k < limits::kReadyLookahead && !q.empty(); ++k) {
            ReadyItem x = q.top();
            q.pop();
            const Node& n = nodes[x.node];
            int g = layer_group[n.l];
            bool blocked = false;
            if (slot % operation::kEngineCount == operation::kCommunicationEngine &&
                dur[n.l][n.op] > 0 && comm_buffers[g] != 0 && has_comm[g]) {
                i128 allowed = comm_buffers[g] == 1
                                   ? last_comm_end[g] + 1
                                   : std::max(last_comm_end[g], last_comm_start[g] + 1);
                blocked = now < allowed;
            }
            (blocked ? deferred : candidates).push_back(x);
        }
        for (const auto& x : deferred) {
            q.push(x);
        }
        if (candidates.empty()) {
            return -1;
        }
        int best = 0, best_score = 100;
        auto score = [&](const ReadyItem& x) {
            const Node& n = nodes[x.node];
            int g = layer_group[n.l];
            if (engine(n.op) == operation::kComputeEngine) {
                if ((n.op == operation::kSharedForward &&
                     node_done[x.node + operation::kExpertForward - operation::kSharedForward]) ||
                    (n.op == operation::kExpertForward &&
                     node_done[x.node + operation::kSharedForward - operation::kExpertForward])) {
                    return 0;
                }
                if (n.op == operation::kSharedBackward) {
                    if (node_done[x.node + operation::kExpertInputGradient -
                                  operation::kSharedBackward]) {
                        return 0;
                    }
                    if (next_mb < mb && active_mb < W && group_layers[g] > 0 &&
                        remaining[g] < 2 * group_layers[g]) {
                        return 1;
                    }
                    return 3;
                }
                if (n.op == operation::kExpertInputGradient &&
                    node_done[x.node + operation::kSharedBackward -
                              operation::kExpertInputGradient]) {
                    return 0;
                }
                if (n.op == operation::kCombineBackward || n.op == operation::kDispatchBackward) {
                    return 2;
                }
                if (n.op == operation::kExpertWeightGradient ||
                    n.op == operation::kSharedWeightGradient) {
                    return 5;
                }
                return 3;
            }
            if (n.op == operation::kCombineForward || n.op == operation::kDispatchBackward) {
                return 0;
            }
            return 1;  // disp / comb_bwd feed compute-side work
        };
        for (int k = 0; k < (int)candidates.size(); ++k) {
            int sc = score(candidates[k]);
            if (sc < best_score ||
                (sc == best_score && (candidates[k].tail > candidates[best].tail ||
                                      (candidates[k].tail == candidates[best].tail &&
                                       candidates[k].p1 < candidates[best].p1)))) {
                best = k;
                best_score = sc;
            }
        }
        int selected = candidates[best].node;
        for (int k = 0; k < (int)candidates.size(); ++k) {
            if (k != best) {
                q.push(candidates[k]);
            }
        }
        return selected;
    };
    auto try_admit = [&]() {
        bool changed = false;
        while (next_mb < mb && (window_release == 1 ? windows_in_use < W : active_mb < W)) {
            bool ok = true;
            for (int g = 0; g < G; ++g) {
                if (remaining[g] < group_layers[g]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) {
                break;
            }
            for (int g = 0; g < G; ++g) {
                remaining[g] -= group_layers[g];
            }
            int m = next_mb++;
            ++active_mb;
            mb_active[m] = 1;
            changed = true;
            if (window_release == 1) {
                ++windows_in_use;
            }
            for (int l = 0; l < L; ++l) {
                for (int o = 0; o < operation::kCount; ++o) {
                    int id = idof(m, l, o);
                    if (nodes[id].indeg == 0) {
                        make_ready(id);
                    }
                }
            }
        }
        return changed;
    };
    try_admit();

    auto complete_node = [&](int id, i128 t) {
        const Node& n = nodes[id];
        int g = layer_group[n.l];
        node_done[id] = 1;
        ++done_mb[n.mb];
        ++finished;
        if (window_release == 1 && n.op == operation::kSharedBackward && g == 0) {
            ++done_sbwd[0][n.mb];
            if (done_sbwd[0][n.mb] == group_layers[0] && !window_released[n.mb]) {
                window_released[n.mb] = 1;
                --windows_in_use;
                try_admit();
            }
        }
        for (int v : out_edges[id]) {
            if (--nodes[v].indeg == 0) {
                make_ready(v);
            }
        }
        if (done_mb[n.mb] == L * operation::kCount) {
            if (window_release == 1 && !window_released[n.mb]) {
                window_released[n.mb] = 1;
                --windows_in_use;
            }
            mb_active[n.mb] = 0;
            --active_mb;
            try_admit();
        }
        (void)g;
        (void)t;
    };

    i128 now = 0;
    while (finished < N) {
        // Close all events at this timestamp before scheduling fresh work.
        bool did_event = false;
        while (!events.empty() && events.top().t == now) {
            Event e = events.top();
            events.pop();
            did_event = true;
            if (e.kind == limits::kEventCompletion) {
                busy[operation::kEngineCount * layer_group[nodes[e.node].l] +
                     engine(nodes[e.node].op)] = 0;
                complete_node(e.node, now);
            } else {
                remaining[e.group] = std::min(activation_capacity[e.group], remaining[e.group] + 1);
                try_admit();
            }
        }

        bool started_any = false, zero_started = false;
        // At most one positive-duration operation per engine; zero-duration
        // nodes close immediately and can expose more work at this same time.
        for (int g = 0; g < G; ++g) {
            for (int e = 0; e < operation::kEngineCount; ++e) {
                int slot = operation::kEngineCount * g + e;
                while (!busy[slot] && !ready[slot].empty()) {
                    int id = ready[slot].top().node;
                    const Node& n = nodes[id];
                    const i128 d = dur[n.l][n.op];
                    if (mode != 2 && e == operation::kCommunicationEngine && d > 0 &&
                        comm_buffers[g] != 0 && has_comm[g]) {
                        i128 allowed = comm_buffers[g] == 1
                                           ? last_comm_end[g] + 1
                                           : std::max(last_comm_end[g], last_comm_start[g] + 1);
                        if (now < allowed) {
                            break;
                        }
                    }
                    id = take_ready(slot, now);
                    if (id < 0) {
                        break;
                    }
                    const Node& chosen = nodes[id];
                    const i128 chosen_d = dur[chosen.l][chosen.op];
                    i128 end = now + chosen_d;
                    out.push_back(Op{now, chosen.mb, chosen.l, chosen.op});
                    if (end > makespan) {
                        makespan = end;
                    }
                    started_any = true;
                    if (e == operation::kCommunicationEngine && chosen_d > 0 &&
                        comm_buffers[g] != 0) {
                        has_comm[g] = 1;
                        last_comm_start[g] = now;
                        last_comm_end[g] = end;
                    }
                    if (chosen.op == operation::kSharedBackward) {
                        events.push(Event{now + 1, limits::kReservationReturn, -1, g});
                    }
                    if (chosen_d == 0) {
                        zero_started = true;
                        complete_node(id, now);
                        // Keep consuming ready zero-work nodes on this engine.
                    } else {
                        busy[slot] = 1;
                        events.push(Event{end, limits::kEventCompletion, id, -1});
                        break;
                    }
                }
            }
        }
        if (finished >= N) {
            break;
        }
        if (zero_started) {
            continue;
        }

        // If zero-time closure exposed work on engines visited earlier, repeat
        // the same timestamp. Otherwise advance to the earliest real event or
        // communication cooldown expiry.
        bool ready_now = false;
        for (int s = 0; s < operation::kEngineCount * G; ++s) {
            if (!busy[s] && !ready[s].empty()) {
                int g = s / operation::kEngineCount, e = s % operation::kEngineCount;
                const Node& top = nodes[ready[s].top().node];
                if (e == operation::kComputeEngine || dur[top.l][top.op] == 0 ||
                    comm_buffers[g] == 0 || !has_comm[g]) {
                    ready_now = true;
                    break;
                }
                i128 allow = comm_buffers[g] == 1
                                 ? last_comm_end[g] + 1
                                 : std::max(last_comm_end[g], last_comm_start[g] + 1);
                if (allow <= now) {
                    ready_now = true;
                    break;
                }
            }
        }
        if (ready_now) {
            continue;
        }

        bool has_next = false;
        i128 nxt = 0;
        if (!events.empty()) {
            nxt = events.top().t;
            has_next = true;
        }
        for (int g = 0; g < G; ++g) {
            int s = operation::kEngineCount * g + operation::kCommunicationEngine;
            if (!busy[s] && !ready[s].empty() && comm_buffers[g] != 0 && has_comm[g] &&
                dur[nodes[ready[s].top().node].l][nodes[ready[s].top().node].op] > 0) {
                i128 allow = comm_buffers[g] == 1
                                 ? last_comm_end[g] + 1
                                 : std::max(last_comm_end[g], last_comm_start[g] + 1);
                if (allow > now && (!has_next || allow < nxt)) {
                    nxt = allow;
                    has_next = true;
                }
            }
        }
        if (!has_next || nxt < now) {
            return false;
        }
        // A same-time event can arise from a zero-duration reservation return
        // only if its timestamp arithmetic was malformed; process safely.
        if (nxt == now && !did_event && !started_any) {
            return false;
        }
        now = nxt;
    }

    std::stable_sort(out.begin(), out.end(), [](const Op& a, const Op& b) {
        if (a.start != b.start) {
            return a.start < b.start;
        }
        return std::tie(a.mb, a.l, a.op) < std::tie(b.mb, b.l, b.op);
    });
    return (int)out.size() == N;
}
}  // namespace event_sched
