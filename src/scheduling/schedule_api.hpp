#pragma once
#include "../common.hpp"
#include "../model/scheduled_operation.hpp"

namespace scheduling {
using i128 = __int128_t;
using Durations = std::vector<std::array<i128, operation::kCount>>;

// Non-owning view shared by the scheduler strategies. All referenced data must
// outlive the schedule call; constructing the view copies no problem data.
struct ProblemView {
    int mb;
    int layers;
    int groups;
    const std::vector<int>& layer_group;
    const Durations& durations;
    const std::vector<int>& group_layers;
};

struct ScheduleOutput {
    std::vector<solver::ScheduledOperation>& operations;
    i128& makespan;
    std::vector<i128>* starts = nullptr;
    std::vector<i128>* ends = nullptr;
};

enum class ListRankMode : int {
    kLegacy = 0,
    kWavefront = 1,
    kDagPitch = 2,
    kRandomKey = 3,
    kNonuniformMicrobatchOffsets = 5,
};
inline constexpr int kMicrobatchOffsetScaleDenominator = 64;

struct EventConfig {
    const std::vector<int>* activation_capacity = nullptr;
    const std::vector<int>* communication_buffers = nullptr;
    int window = 0;
    int mode = 0;
    int fill_groups = 0;
    int fill_microbatches = 0;
    int reward_tenths = 0;
    bool flat_reward = false;
    int window_release = 0;
};

struct ListConfig {
    int window = 1;
    int variant = 0;
    bool early = false;
    int gap = 0;
    int fill_groups = 0;
    int fill_microbatches = 0;
    i128 busy = 0;
    int ratio_tenths = 0;
    bool ramp = false;
    bool wave_rank = false;
    bool fill_gaps = false;
    int rank_mode = 0;
    int rank_a = 1;
    int rank_b = 1;
    int phase = 0;
    int pitch_numerator = 1;
    int pitch_denominator = 1;
    int duration_head = 0;
    bool microbatch_descending = false;
    int weight_gradient_order = 0;
    ListRankMode priority_mode = ListRankMode::kLegacy;
    std::uint64_t random_seed = 0;
    int random_jitter_span = 1;
    int random_wave_stride = 1;
    std::vector<i128> microbatch_offset_ticks;
    int microbatch_offset_denominator = kMicrobatchOffsetScaleDenominator;
};

struct EventScheduleStrategy {
    using Config = EventConfig;
    static bool schedule(const ProblemView& problem, const EventConfig& config,
                         ScheduleOutput& output);
};

struct ListScheduleStrategy {
    using Config = ListConfig;
    static bool schedule(const ProblemView& problem, const ListConfig& config,
                         ScheduleOutput& output);
};

// Compile-time strategy context: policy selection is resolved by the compiler,
// with no virtual calls or per-operation dispatch in the scheduler kernels.
template <class Strategy>
class Scheduler {
public:
    explicit Scheduler(ProblemView problem) : problem_(problem) {}

    bool run(const typename Strategy::Config& config, ScheduleOutput& output) const {
        return Strategy::schedule(problem_, config, output);
    }

private:
    ProblemView problem_;
};
}  // namespace scheduling
