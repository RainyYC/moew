#include "priority_search.hpp"

#include "schedule_validation.hpp"
#include "../placement/expert_mapping.hpp"
#include "../scheduling/schedule_api.hpp"

#include <random>

namespace solver {
namespace {
using Clock = std::chrono::steady_clock;
using RankConfig = scheduling::ListConfig;
inline constexpr int kPitchSampleLimit = 48;
inline constexpr int kWaveSampleLimit = 32;
inline constexpr int kRandomKeySampleCount = 32;
inline constexpr int kPriorityTrialLimit = 96;
inline constexpr int kOffsetRandomPerturbationLimit = 64;
inline constexpr int kOffsetCoordinateLimit = 240;
inline constexpr int kOffsetCoordinateScaleCount = 8;
inline constexpr int kMinRandomOffsetMoves = 2;
inline constexpr int kRandomOffsetMoveCount = 3;
inline constexpr int kPriorityConfigShareNumerator = 3;
inline constexpr int kPriorityConfigShareDenominator = 5;

struct TrialConfig {
    RankConfig config;
    bool is_pitch = false;
};

std::uint64_t layout_seed(const InputData& x, const ScheduleResult& seed) {
    std::uint64_t hash = 1469598103934665603ULL;
    const auto add = [&hash](std::uint64_t value) {
        hash ^= value;
        hash *= 1099511628211ULL;
    };
    add(static_cast<std::uint64_t>(x.mb));
    add(static_cast<std::uint64_t>(x.L));
    add(static_cast<std::uint64_t>(seed.G));
    add(static_cast<std::uint64_t>(seed.c.P));
    for (int cut : seed.cuts) {
        add(static_cast<std::uint64_t>(cut));
    }
    for (int group : seed.group) {
        add(static_cast<std::uint64_t>(group));
    }
    for (const auto& row : seed.c.map) {
        for (int value : row) {
            add(static_cast<std::uint64_t>(value));
        }
    }
    return hash;
}

std::vector<int> windows_for(const InputData& x, int groups) {
    std::vector<int> windows = {1, 2, 4, 8, groups, 2 * groups,
                                std::max(1, x.mb / 2), x.mb};
    windows.erase(std::remove_if(windows.begin(), windows.end(), [&](int value) {
                      return value <= 0 || value > x.mb;
                  }),
                  windows.end());
    std::sort(windows.begin(), windows.end());
    windows.erase(std::unique(windows.begin(), windows.end()), windows.end());
    return windows;
}

std::vector<TrialConfig> make_configs(const InputData& x, int groups,
                                      std::mt19937_64& random) {
    std::vector<TrialConfig> core_pitch;
    const std::array<std::array<int, 4>, 6> core_parameters = {{
        {{3, 4, 0, 0}}, {{8, 1, 2, 2}}, {{2, 1, 1, 0}},
        {{2, 1, 2, 2}}, {{4, 1, 1, 2}}, {{4, 3, 2, 1}},
    }};
    for (const auto& parameters : core_parameters) {
        TrialConfig trial;
        trial.config.window = x.mb;
        trial.config.fill_gaps = true;
        trial.config.priority_mode = scheduling::ListRankMode::kDagPitch;
        trial.config.pitch_numerator = parameters[0];
        trial.config.pitch_denominator = parameters[1];
        trial.config.duration_head = parameters[2];
        trial.config.weight_gradient_order = parameters[3];
        trial.is_pitch = true;
        core_pitch.push_back(trial);
    }

    std::vector<TrialConfig> wave;
    const std::vector<int> multipliers = {1, 2, 4, 8, 16};
    const std::vector<int> strides = {0, 1, 2, 4, 8};
    const std::vector<int> phases = {-4, -2, 0, 2, 4};
    const std::vector<int> gradients = {0, 1, 2};
    const auto windows = windows_for(x, groups);
    for (int a : multipliers) {
        for (int b : strides) {
            for (int phase : phases) {
                for (int gradient : gradients) {
                    for (int window : windows) {
                        TrialConfig trial;
                        trial.config.window = window;
                        trial.config.fill_gaps = true;
                        trial.config.priority_mode = scheduling::ListRankMode::kWavefront;
                        trial.config.rank_a = a;
                        trial.config.rank_b = b;
                        trial.config.phase = phase;
                        trial.config.weight_gradient_order = gradient;
                        wave.push_back(trial);
                    }
                }
            }
        }
    }
    std::shuffle(wave.begin(), wave.end(), random);
    if (wave.size() > kWaveSampleLimit) {
        wave.resize(kWaveSampleLimit);
    }

    std::vector<TrialConfig> pitch;
    const std::vector<std::pair<int, int>> ratios = {
        {1, 32}, {1, 16}, {1, 8}, {1, 4}, {1, 2}, {1, 1}, {2, 1}, {4, 1},
        {8, 1},  {16, 1}, {32, 1}, {2, 3}, {3, 2}, {3, 4}, {4, 3}};
    for (const auto& ratio : ratios) {
        for (int head : {0, 1, 2}) {
            for (int gradient : gradients) {
                for (int window : windows) {
                    TrialConfig trial;
                    trial.config.window = window;
                    trial.config.fill_gaps = true;
                    trial.config.priority_mode = scheduling::ListRankMode::kDagPitch;
                    trial.config.pitch_numerator = ratio.first;
                    trial.config.pitch_denominator = ratio.second;
                    trial.config.duration_head = head;
                    trial.config.weight_gradient_order = gradient;
                    trial.is_pitch = true;
                    pitch.push_back(trial);
                }
            }
        }
    }
    std::shuffle(pitch.begin(), pitch.end(), random);
    if (pitch.size() > kPitchSampleLimit) {
        pitch.resize(kPitchSampleLimit);
    }

    std::vector<TrialConfig> random_keys;
    const std::vector<int> jitter_spans = {1, 8, 32, 128, 512, 2048};
    const std::vector<int> random_strides = {0, 1, 2, 4, 8, 16, 32};
    for (int trial_id = 0; trial_id < kRandomKeySampleCount; ++trial_id) {
        TrialConfig trial;
        trial.config.window = windows[trial_id % windows.size()];
        trial.config.fill_gaps = true;
        trial.config.priority_mode = scheduling::ListRankMode::kRandomKey;
        trial.config.random_seed = random();
        trial.config.random_jitter_span =
            jitter_spans[static_cast<std::size_t>(random() % jitter_spans.size())];
        trial.config.random_wave_stride =
            random_strides[static_cast<std::size_t>(random() % random_strides.size())];
        trial.config.weight_gradient_order = static_cast<int>(random() % 3);
        random_keys.push_back(trial);
    }

    std::vector<TrialConfig> configs = std::move(core_pitch);
    configs.insert(configs.end(), wave.begin(), wave.end());
    configs.insert(configs.end(), pitch.begin(), pitch.end());
    configs.insert(configs.end(), random_keys.begin(), random_keys.end());
    std::shuffle(configs.begin() + static_cast<std::ptrdiff_t>(core_parameters.size()),
                 configs.end(), random);
    return configs;
}

bool run_trial(const InputData& x, const ScheduleResult& layout,
               const std::vector<std::array<i128, operation::kCount>>& durations,
               const std::vector<int>& group_layers, const RankConfig& config,
               Clock::time_point deadline, ScheduleResult& candidate) {
    if (Clock::now() >= deadline) {
        return false;
    }
    scheduling::ProblemView problem{x.mb, x.L, layout.G, layout.group, durations, group_layers};
    scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
    std::vector<event_sched::Op> operations;
    i128 time = 0;
    scheduling::ScheduleOutput output{operations, time};
    if (!scheduler.run(config, output) || Clock::now() >= deadline) {
        return false;
    }
    std::stable_sort(operations.begin(), operations.end(), [](const auto& left, const auto& right) {
        return std::tie(left.start, left.mb, left.l, left.op) <
               std::tie(right.start, right.mb, right.l, right.op);
    });
    candidate = layout;
    candidate.ops = std::move(operations);
    candidate.time = time;
    const bool feasible = is_feasible_schedule(x, candidate);
    return feasible && Clock::now() < deadline;
}

std::vector<i128> uniform_offsets(int microbatches) {
    std::vector<i128> offsets(microbatches, 0);
    for (int mb = 1; mb < microbatches; ++mb) {
        offsets[mb] =
            static_cast<i128>(mb) * scheduling::kMicrobatchOffsetScaleDenominator;
    }
    return offsets;
}

void refine_offsets(const InputData& x, const ScheduleResult& layout,
                    const std::vector<std::array<i128, operation::kCount>>& durations,
                    const std::vector<int>& group_layers, const RankConfig& pitch_config,
                    std::mt19937_64& random, Clock::time_point deadline, ScheduleResult& best) {
    if (x.mb < 2 || Clock::now() >= deadline) {
        return;
    }
    std::vector<i128> offsets = uniform_offsets(x.mb);
    RankConfig config = pitch_config;
    config.priority_mode = scheduling::ListRankMode::kNonuniformMicrobatchOffsets;
    config.microbatch_offset_ticks = offsets;
    config.microbatch_offset_denominator = scheduling::kMicrobatchOffsetScaleDenominator;
    ScheduleResult current;
    if (!run_trial(x, layout, durations, group_layers, config, deadline, current)) {
        return;
    }
    if (current.time < best.time) {
        best = current;
    }

    const std::array<int, 5> phases = {-2, -1, 0, 1, 2};
    for (int phase : phases) {
        if (Clock::now() >= deadline) {
            return;
        }
        RankConfig phase_config = config;
        phase_config.phase = phase;
        ScheduleResult candidate;
        if (!run_trial(x, layout, durations, group_layers, phase_config, deadline, candidate)) {
            continue;
        }
        if (candidate.time < current.time) {
            current = candidate;
            config = phase_config;
        }
        if (candidate.time < best.time) {
            best = std::move(candidate);
        }
    }

    const std::array<int, kOffsetCoordinateScaleCount> deltas = {
        -1, 1, -4, 4, -16, 16, -64, 64};
    int coordinate_trials = 0;
    for (int delta : deltas) {
        for (int mb = 1; mb < x.mb && coordinate_trials < kOffsetCoordinateLimit; ++mb) {
            for (bool move_suffix : {false, true}) {
                if (Clock::now() >= deadline || coordinate_trials >= kOffsetCoordinateLimit) {
                    break;
                }
                ++coordinate_trials;
                std::vector<i128> next_offsets = offsets;
                if (!move_suffix) {
                    next_offsets[mb] += delta;
                } else {
                    for (int index = mb; index < x.mb; ++index) {
                        next_offsets[index] += delta;
                    }
                }
                if (next_offsets[mb] < 0 ||
                    !std::is_sorted(next_offsets.begin(), next_offsets.end())) {
                    continue;
                }
                RankConfig candidate_config = config;
                candidate_config.microbatch_offset_ticks = next_offsets;
                ScheduleResult candidate;
                if (!run_trial(x, layout, durations, group_layers, candidate_config, deadline,
                               candidate)) {
                    continue;
                }
                if (candidate.time < current.time) {
                    current = candidate;
                    offsets.swap(next_offsets);
                    config = candidate_config;
                }
                if (candidate.time < best.time) {
                    best = std::move(candidate);
                }
            }
        }
        if (coordinate_trials >= kOffsetCoordinateLimit || Clock::now() >= deadline) {
            break;
        }
    }

    for (int trial = 0; trial < kOffsetRandomPerturbationLimit && Clock::now() < deadline;
         ++trial) {
        std::vector<i128> next_offsets = offsets;
        const int move_count =
            kMinRandomOffsetMoves + static_cast<int>(random() % kRandomOffsetMoveCount);
        for (int move = 0; move < move_count; ++move) {
            const int mb = 1 + static_cast<int>(random() % (x.mb - 1));
            const int delta = deltas[static_cast<std::size_t>(random() % deltas.size())];
            const bool move_suffix = (random() & 1U) != 0;
            if (!move_suffix) {
                next_offsets[mb] += delta;
            } else {
                for (int index = mb; index < x.mb; ++index) {
                    next_offsets[index] += delta;
                }
            }
        }
        if (next_offsets[0] != 0 ||
            !std::is_sorted(next_offsets.begin(), next_offsets.end())) {
            continue;
        }
        RankConfig candidate_config = config;
        candidate_config.microbatch_offset_ticks = next_offsets;
        ScheduleResult candidate;
        if (!run_trial(x, layout, durations, group_layers, candidate_config, deadline,
                       candidate)) {
            continue;
        }
        if (candidate.time < current.time) {
            current = candidate;
            offsets.swap(next_offsets);
            config = candidate_config;
        }
        if (candidate.time < best.time) {
            best = std::move(candidate);
        }
    }
}
}  // namespace

void refine_priority_schedules(const InputData& x, const std::vector<ScheduleResult>& seeds,
                               ScheduleResult& best, Clock::time_point deadline) {
    const i128 node_count = static_cast<i128>(x.mb) * x.L * operation::kCount;
    if (x.mb <= 0 || x.mb > search_limits::kExtraLayoutMicrobatchLimit ||
        node_count > search_limits::kExtraLayoutNodeLimit || deadline <= Clock::now()) {
        return;
    }

    std::vector<ScheduleResult> layouts;
    layouts.reserve(seeds.size() + 1);
    auto normalize = [](const ScheduleResult& schedule) {
        ScheduleResult normalized = schedule;
        std::stable_sort(normalized.ops.begin(), normalized.ops.end(),
                         [](const auto& left, const auto& right) {
                             return std::tie(left.start, left.mb, left.l, left.op) <
                                    std::tie(right.start, right.mb, right.l, right.op);
                         });
        return normalized;
    };
    if (!best.ops.empty()) {
        ScheduleResult normalized_best = normalize(best);
        if (is_feasible_schedule(x, normalized_best)) {
            layouts.push_back(std::move(normalized_best));
        }
    }
    for (const auto& seed : seeds) {
        if (Clock::now() >= deadline) {
            return;
        }
        if (seed.ops.empty()) {
            continue;
        }
        ScheduleResult normalized_seed = normalize(seed);
        if (is_feasible_schedule(x, normalized_seed)) {
            layouts.push_back(std::move(normalized_seed));
        }
    }
    if (layouts.empty()) {
        return;
    }

    std::set<std::vector<int>> seen_layouts;
    layouts.erase(std::remove_if(layouts.begin(), layouts.end(), [&](const ScheduleResult& layout) {
                     std::vector<int> key = layout.cuts;
                     key.push_back(layout.c.P);
                     key.insert(key.end(), layout.group.begin(), layout.group.end());
                     for (const auto& row : layout.c.map) {
                         key.insert(key.end(), row.begin(), row.end());
                     }
                     if (!seen_layouts.insert(std::move(key)).second) {
                         return true;
                     }
                     return false;
                 }),
                 layouts.end());

    for (std::size_t layout_index = 0; layout_index < layouts.size(); ++layout_index) {
        const auto& layout = layouts[layout_index];
        if (Clock::now() >= deadline) {
            break;
        }
        const auto remaining_time = deadline - Clock::now();
        const auto remaining_layouts = layouts.size() - layout_index;
        const Clock::time_point layout_deadline =
            Clock::now() + remaining_time / static_cast<Clock::duration::rep>(remaining_layouts);
        if (layout.G <= 0 || static_cast<int>(layout.group.size()) != x.L) {
            continue;
        }
        std::vector<int> group_layers(layout.G, 0);
        for (int group : layout.group) {
            if (group < 0 || group >= layout.G) {
                group_layers.clear();
                break;
            }
            ++group_layers[group];
        }
        if (static_cast<int>(group_layers.size()) != layout.G) {
            continue;
        }
        const auto durations = compute_durations(x, layout.c);
        std::mt19937_64 random(layout_seed(x, layout));
        std::vector<TrialConfig> configs = make_configs(x, layout.G, random);
        // Reserve at least two-fifths of this layout's remaining budget for
        // nonuniform offsets and phase search, even when list trials are slow.
        const auto config_remaining = layout_deadline - Clock::now();
        const Clock::time_point config_deadline =
            Clock::now() + config_remaining * kPriorityConfigShareNumerator /
                               kPriorityConfigShareDenominator;
        int evaluated = 0;
        RankConfig best_pitch_config;
        i128 layout_pitch_time = search_limits::kInfiniteTime;
        for (const auto& trial : configs) {
            if (Clock::now() >= config_deadline || evaluated >= kPriorityTrialLimit) {
                break;
            }
            ++evaluated;
            ScheduleResult candidate;
            if (!run_trial(x, layout, durations, group_layers, trial.config, config_deadline,
                           candidate)) {
                continue;
            }
            if (trial.is_pitch && candidate.time < layout_pitch_time) {
                layout_pitch_time = candidate.time;
                best_pitch_config = trial.config;
            }
            if (candidate.time < best.time) {
                best = std::move(candidate);
            }
        }
        if (layout_pitch_time < search_limits::kInfiniteTime && Clock::now() < layout_deadline) {
            refine_offsets(x, layout, durations, group_layers, best_pitch_config, random,
                           layout_deadline, best);
        }
    }
}
}  // namespace solver
