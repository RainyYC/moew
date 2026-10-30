#include "list_scheduler.hpp"

#include "../common.hpp"
#include "../core/operation_graph.hpp"
#include "schedule_api.hpp"

// ===== list_scheduler =====
namespace list_sched {
struct Variant {
    bool fwd_first;
    bool mb_desc;
    bool l_desc;
    bool l_major;
};
static const std::array<Variant, limits::kVariantCount> VARIANTS = {{{true, false, false, false},
                                                                     {true, false, true, false},
                                                                     {true, true, false, false},
                                                                     {true, true, true, false},
                                                                     {false, false, false, false},
                                                                     {false, true, true, false},
                                                                     {true, false, false, true},
                                                                     {false, true, false, true}}};
struct Item {
    int id;
    i128 early;
    std::array<i128, 4> rank;
};
struct Later {
    bool operator()(Item const& a, Item const& b) const {
        if (a.early != b.early) {
            return a.early > b.early;
        }
        if (a.rank != b.rank) {
            return a.rank > b.rank;
        }
        return a.id > b.id;
    }
};
bool schedule(int mb, int L, int G, const std::vector<int>& grp, const Dur& d,
              const std::vector<int>& ng, int W, int vi, bool early, int gap, int fs, int fm,
              i128 busy, int ratio10, bool ramp, std::vector<Op>& out, i128& tm,
              std::vector<i128>* starts, std::vector<i128>* ends, bool wave_rank, bool fill_gaps,
              int rank_mode, int A, int B, int phase, int pitch_num, int pitch_den,
              int duration_head, bool mb_desc, int dw_order) {
    (void)mb_desc;  // Kept in the stable scheduler call signature; currently not used.
    if (mb < 1 || L < 1 || G < 1 || vi < 0 || vi >= limits::kVariantCount) {
        return false;
    }
    W = std::max(1, std::min(W, mb));
    int stride = L * operation::kCount, N = mb * stride;
    if ((int)grp.size() != L || (int)d.size() != L) {
        return false;
    }
    auto id = [](int m, int l, int o, int L) { return operation_graph::node_id(m, l, o, L); };
    using Topo = std::pair<std::vector<std::vector<int>>, std::vector<std::vector<int>>>;
    static std::map<std::pair<int, int>, Topo> cache;
    auto key = std::make_pair(mb, L);
    auto it = cache.find(key);
    if (it == cache.end()) {
        Topo t;
        t.first.resize(N);
        t.second.resize(N);
        auto edge = [&](int a, int b) {
            t.second[a].push_back(b);
            t.first[b].push_back(a);
        };
        auto graph_id = [L](int m, int l, int o) { return operation_graph::node_id(m, l, o, L); };
        for (int m = 0; m < mb; m++) {
            for (int l = 0; l < L; l++) {
                operation_graph::append_layer_edges(m, l, L, graph_id, edge);
            }
        }
        it = cache.emplace(key, std::move(t)).first;
    }
    auto const& pred = it->second.first;
    auto const& succ = it->second.second;
    auto v = VARIANTS[vi];
    std::vector<int> rem(N);
    for (int i = 0; i < N; i++) {
        rem[i] = pred[i].size();
    }
    std::vector<char> pushed(N);
    std::vector<i128> st(N, -1), en(N, -1), cf(G), mf(G);
    std::vector<int> bw(G * mb);
    std::vector<i128> rel(G * mb, -1);
    for (int g = 0; g < G; g++) {
        for (int m = 0; m < mb; m++) {
            bw[g * mb + m] = ng[g];
        }
    }
    std::vector<i128> h, h_finish, layer_prefix;
    i128 max_work = 0;
    if (rank_mode == 2) {
        h.resize(N);
        h_finish.resize(N);
        layer_prefix.resize(L + 1);
        std::vector<int> rh(N);
        std::queue<int> tq;
        for (int x = 0; x < N; x++) {
            rh[x] = pred[x].size();
            if (!rh[x]) {
                tq.push(x);
            }
        }
        while (!tq.empty()) {
            int x = tq.front();
            tq.pop();
            i128 finish = h[x] + d[(x % stride) / operation::kCount][x % operation::kCount];
            h_finish[x] = finish;
            for (int y : succ[x]) {
                h[y] = std::max(h[y], finish);
                if (--rh[y] == 0) {
                    tq.push(y);
                }
            }
        }
        for (int l = 0; l < L; l++) {
            i128 a = 0, bw = 0, total = 0;
            for (int o = 0; o < operation::kCount; o++) {
                (comm(o) ? bw : a) += d[l][o];
                total += d[l][o];
            }
            max_work = std::max(max_work, std::max(a, bw));
            layer_prefix[l + 1] = layer_prefix[l] + (total + 9) / 10;
        }
    }
    auto rank = [&](int x) {
        int m = x / stride, z = x % stride, l = z / operation::kCount, o = z % operation::kCount;
        i128 dw = 0;
        if ((o == operation::kExpertWeightGradient || o == operation::kSharedWeightGradient) &&
            dw_order == 1) {
            dw = d[l][o];
        } else if ((o == operation::kExpertWeightGradient ||
                    o == operation::kSharedWeightGradient) &&
                   dw_order == 2) {
            dw = -d[l][o];
        }
        if (rank_mode == 1) {
            i128 forward = (i128)A * m +
                           (i128)B * (o < operation::kSharedBackward ? l : 2 * L - l) +
                           (o >= operation::kSharedBackward ? (i128)phase * L / 2 : 0);
            return std::array<i128, 4>{
                (o == operation::kExpertWeightGradient || o == operation::kSharedWeightGradient)
                    ? 1
                    : 0,
                forward, dw, o};
        }
        if (rank_mode == 2) {
            i128 topology =
                duration_head == 1
                    ? h[x]
                    : (duration_head == 2 ? h_finish[x] : layer_prefix[l] + (d[l][o] + 9) / 10);
            return std::array<i128, 4>{
                (o == operation::kExpertWeightGradient || o == operation::kSharedWeightGradient)
                    ? 1
                    : 0,
                (i128)m * max_work * pitch_num + topology * pitch_den, dw, o};
        }
        if (wave_rank) {
            return std::array<i128, 4>{
                (o == operation::kExpertWeightGradient || o == operation::kSharedWeightGradient)
                    ? 1
                    : 0,
                m + (o < operation::kSharedBackward ? l : 2 * L - l), o, 0};
        }
        i128 head = ((o <= operation::kCombineForward) == v.fwd_first) ? 0 : 1;
        i128 mk = v.mb_desc ? -m : m, lk = v.l_desc ? -l : l;
        return v.l_major ? std::array<i128, 4>{head, lk, mk, o}
                         : std::array<i128, 4>{head, mk, lk, o};
    };
    auto earliest = [&](int x) {
        int m = x / stride, z = x % stride, l = z / operation::kCount, o = z % operation::kCount,
            g = grp[l];
        i128 t = 0;
        for (int p : pred[x]) {
            t = std::max(t, en[p]);
        }
        if (l == 0 && pred[x].empty() && m >= W) {
            t = std::max(t, rel[g * mb + m - W]);
        }
        return std::max(t, comm(o) ? mf[g] : cf[g]);
    };
    i128 den = early ? (i128)10 * (ramp ? std::max(1, fs) * std::max(1, fm) : 1) : 1;
    auto keyof = [&](int x, i128 ready) {
        int m = x / stride, l = (x % stride) / operation::kCount, o = x % operation::kCount;
        if (!early || o > operation::kCombineForward || m >= fm || grp[l] >= fs) {
            return ready * den;
        }
        i128 factor = ramp ? (i128)(fs - grp[l]) * (fm - m) : 1;
        return ready * den - busy * ratio10 * factor;
    };
    std::priority_queue<Item, std::vector<Item>, Later> q;
    auto push = [&](int x) {
        if (pushed[x]) {
            return;
        }
        int m = x / stride, l = (x % stride) / operation::kCount;
        if (l == 0 && pred[x].empty() && m >= W && bw[grp[l] * mb + m - W] > 0) {
            return;
        }
        pushed[x] = 1;
        q.push({x, early ? keyof(x, earliest(x)) : 0, rank(x)});
    };
    for (int x = 0; x < N; x++) {
        if (pred[x].empty()) {
            push(x);
        }
    }
    std::vector<std::array<std::vector<std::pair<i128, i128>>, 2>> gaps(G);
    out.clear();
    tm = 0;
    int count = 0;
    while (count < N) {
        if (q.empty()) {
            return false;
        }
        Item it = q.top();
        q.pop();
        int x = it.id, m = x / stride, z = x % stride, l = z / operation::kCount,
            o = z % operation::kCount, g = grp[l], eng = comm(o) ? 1 : 0;
        i128 ready = 0;
        for (int p : pred[x]) {
            ready = std::max(ready, en[p]);
        }
        if (l == 0 && pred[x].empty() && m >= W) {
            ready = std::max(ready, rel[g * mb + m - W]);
        }
        i128 key = keyof(x, ready);
        if (early && !q.empty() && key > q.top().early) {
            q.push({x, key, it.rank});
            continue;
        }
        i128 free = comm(o) ? mf[g] : cf[g];
        int slot = -1;
        if (fill_gaps && d[l][o] && gap == 0) {
            auto& a = gaps[g][eng];
            auto itg =
                std::upper_bound(a.begin(), a.end(), std::make_pair(ready, (i128(1) << 126)));
            for (; itg != a.end(); ++itg) {
                if (std::max(ready, itg->second) + d[l][o] <= itg->first) {
                    slot = (int)(itg - a.begin());
                    ready = std::max(ready, itg->second);
                    break;
                }
            }
        }
        if (slot < 0 && free > ready) {
            ready = free;
        }
        key = keyof(x, ready);
        if (early && !q.empty() && key > q.top().early) {
            q.push({x, key, it.rank});
            continue;
        }
        st[x] = ready;
        en[x] = ready + d[l][o];
        tm = std::max(tm, en[x]);
        out.push_back({ready, m, l, o});
        if (d[l][o]) {
            if (fill_gaps && gap == 0) {
                auto& a = gaps[g][eng];
                if (slot >= 0) {
                    auto [stop, begin] = a[slot];
                    a.erase(a.begin() + slot);
                    int pos = slot;
                    if (begin < ready) {
                        a.insert(a.begin() + pos, {ready, begin});
                        pos++;
                    }
                    if (en[x] < stop) {
                        a.insert(a.begin() + pos, {stop, en[x]});
                    }
                } else if (free < ready) {
                    auto itg =
                        std::lower_bound(a.begin(), a.end(), std::make_pair(ready, (i128)-1));
                    a.insert(itg, {ready, free});
                }
            }
            if (comm(o)) {
                mf[g] = std::max(mf[g], en[x] + gap);
            } else {
                cf[g] = std::max(cf[g], en[x]);
            }
        } else if (comm(o) && gap) {
            mf[g] = std::max(mf[g], en[x] + gap);
        }
        count++;
        for (int y : succ[x]) {
            if (--rem[y] == 0) {
                push(y);
            }
        }
        // s_bwd releases the activation reservation after starting, over a closed interval.
        if (o == operation::kSharedBackward) {
            rel[g * mb + m] = std::max(rel[g * mb + m], en[x]);
            if (--bw[g * mb + m] == 0) {
                int nm = m + W;
                if (nm < mb) {
                    for (int oo = 0; oo < operation::kCount; oo++) {
                        int y = id(nm, 0, oo, L);
                        if (pred[y].empty() && rem[y] == 0) {
                            push(y);
                        }
                    }
                }
            }
        }
    }
    if (starts) {
        *starts = std::move(st);
    }
    if (ends) {
        *ends = std::move(en);
    }
    return true;
}
}  // namespace list_sched

namespace scheduling {
bool ListScheduleStrategy::schedule(const ProblemView& problem, const ListConfig& config,
                                    ScheduleOutput& output) {
    return list_sched::schedule(
        problem.mb, problem.layers, problem.groups, problem.layer_group, problem.durations,
        problem.group_layers, config.window, config.variant, config.early, config.gap,
        config.fill_groups, config.fill_microbatches, config.busy, config.ratio_tenths, config.ramp,
        output.operations, output.makespan, output.starts, output.ends, config.wave_rank,
        config.fill_gaps, config.rank_mode, config.rank_a, config.rank_b, config.phase,
        config.pitch_numerator, config.pitch_denominator, config.duration_head,
        config.microbatch_descending, config.weight_gradient_order);
}
}  // namespace scheduling
