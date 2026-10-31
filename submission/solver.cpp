// BEGIN TRANSLATION UNIT: src/solver.cpp
// BEGIN MODULE: src/solver.cpp
// BEGIN MODULE: src/app/solver.hpp
#include <chrono>

// BEGIN MODULE: src/io/options.hpp
// BEGIN MODULE: src/common.hpp

// Shared standard-library dependencies and operation identifiers.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <unordered_set>
#include <utility>
#include <vector>

namespace operation {
enum Code : int {
    kSharedForward = 0,
    kDispatchForward = 1,
    kExpertForward = 2,
    kCombineForward = 3,
    kSharedBackward = 4,
    kCombineBackward = 5,
    kExpertInputGradient = 6,
    kExpertWeightGradient = 7,
    kDispatchBackward = 8,
    kSharedWeightGradient = 9,
};
inline constexpr int kCount = 10;
inline constexpr int index(Code code) {
    return static_cast<int>(code);
}
inline constexpr int kComputeEngine = 0;
inline constexpr int kCommunicationEngine = 1;
inline constexpr int kEngineCount = 2;
inline constexpr int kMaxCommunicationBuffers = 2;
inline constexpr std::array<int, 4> kCommunicationOperations = {
    kDispatchForward, kCombineForward, kCombineBackward, kDispatchBackward};
}  // namespace operation
// END MODULE: src/common.hpp
namespace solver {
enum class SearchMode { kFull, kList, kEvent, kSerial };

struct Options {
    int force_p = 0;
    SearchMode mode = SearchMode::kFull;
    int polish_pass_limit = 0;
    std::string retime_mode = "auto";
    std::string input_path;
    bool help = false;
};
Options parse_options(int argc, char** argv);
}  // namespace solver
// END MODULE: src/io/options.hpp
// BEGIN MODULE: src/model/problem.hpp
// Shared problem and result value types.
// BEGIN MODULE: src/search/limits.hpp

namespace solver::search_limits {
inline constexpr int kDefaultBudgetMs = 9200;
inline constexpr int kMinimumBudgetMs = 9000;
inline constexpr int kMaximumBudgetMs = 9500;
inline constexpr int kWindowExhaustiveMicrobatchLimit = 64;
inline constexpr int kExtraLayoutMicrobatchLimit = 16;
inline constexpr int kExtraLayoutNodeLimit = 8000;
inline constexpr int kWaveDeadlineMs = 9000;
inline constexpr int kPolishPrefixDeadlineMs = 9000;
inline constexpr int kWaveWarmupMs = 8000;
inline constexpr int kWaveExtensionReserveMs = 1000;
inline constexpr int kListNormalDeadlineMs = 8000;
inline constexpr int kListDeepDeadlineMs = 30000;
inline constexpr int kPrefixEvaluationsPerRound = 3000;
inline constexpr int kPrefixNodeLimit = 8000;
inline constexpr int kPrefixMaxRounds = 4;
inline constexpr int kPrefixRoundReserveMs = 100;
inline constexpr int kQuickGapFillLatestStartMs = 4000;
inline constexpr int kListReleaseDeadlineMs = 8000;
struct SearchBudget {
    int list_deadline_ms;
    int wave_deadline_ms;
    int layout_budget_ms;
    int layout_deadline_cap_ms;
    int priority_budget_ms;
    int priority_deadline_cap_ms;
};
inline constexpr SearchBudget kSmallFullSearchBudget{3400, 4200, 2000, 6100, 1600, 7800};
inline constexpr int kExtensionDeadlineReserveMs = 30;
inline constexpr int kExtensionIterationBudget = 700;
inline constexpr int kPlacementSearchBudget = 250000;
inline constexpr int kPlacementPeakSearchSteps = 12;
inline constexpr int kMaximumPartitionCount = 64;
inline constexpr long long kMillion = 1000000LL;
inline constexpr long long kTrillion = 1000000000000LL;
inline constexpr __int128_t kInfiniteTime = static_cast<__int128_t>(1) << 126;
}  // namespace solver::search_limits
// END MODULE: src/search/limits.hpp
// BEGIN MODULE: src/model/scheduled_operation.hpp

namespace solver {
using i128 = __int128_t;

struct Op {
    i128 start;
    int mb;
    int l;
    int op;
};
using ScheduledOperation = Op;
}  // namespace solver

namespace event_sched {
using Op = solver::ScheduledOperation;
}  // namespace event_sched
// END MODULE: src/model/scheduled_operation.hpp
namespace solver {
using i128 = __int128_t;
struct InputData {
    int N, S, L, E, k, mb;
    i128 M, Bi, Bo, Z, Zs, U, Ua, d, b, Fs, Fio, Fin, ax, bx;
    std::vector<i128> T;
    std::vector<std::vector<i128>> load;
};
struct Candidate {
    int P = 0, V = 0;
    i128 score = 0;
    std::vector<int> cuts;
    std::vector<std::vector<int>> map;
};
struct PartitionCandidate {
    Candidate best_v, max_v;
    i128 probe_time = search_limits::kInfiniteTime;
};
struct ScheduleResult {
    Candidate c;
    int G = 0, K = 0;
    i128 time = search_limits::kInfiniteTime;
    std::vector<int> cuts, group;
    std::vector<event_sched::Op> ops;
};

}  // namespace solver
// END MODULE: src/model/problem.hpp
namespace solver {
int run(int argc, char** argv);

class Solver {
public:
    bool solve(const InputData& input, const Options& options,
               std::chrono::steady_clock::time_point main_start, ScheduleResult& result) const;
};
}  // namespace solver
// END MODULE: src/app/solver.hpp

int main(int argc, char** argv) {
    return solver::run(argc, argv);
}
// END MODULE: src/solver.cpp
// END TRANSLATION UNIT: src/solver.cpp
// BEGIN TRANSLATION UNIT: src/app/solver.cpp
// BEGIN MODULE: src/app/solver.cpp
// Top-level phase orchestration; global main stays in solver.cpp.
// BEGIN MODULE: src/io/input.hpp
namespace solver {
InputData read_input(std::istream& in);
}
// END MODULE: src/io/input.hpp
// BEGIN MODULE: src/io/numeric.hpp
namespace solver {
using i128 = __int128_t;
std::istream& operator>>(std::istream& in, i128& v);
inline i128 ceil_div(i128 a, i128 b) {
    return (a + b - 1) / b;
}
std::string to_decimal(i128 x);
}  // namespace solver
// END MODULE: src/io/numeric.hpp
// BEGIN MODULE: src/io/output.hpp
namespace solver {
void write_output(const InputData& x, const ScheduleResult& best, bool serial);
}
// END MODULE: src/io/output.hpp
// BEGIN MODULE: src/search/boost_search.hpp
namespace solver {
ScheduleResult run_boost_borrow(const InputData& x, ScheduleResult best,
                                const ScheduleResult& v5_base, bool serial,
                                const std::string& borrow);
}
// END MODULE: src/search/boost_search.hpp
// BEGIN MODULE: src/search/candidate_search.hpp
namespace solver {
std::vector<PartitionCandidate> generate_candidates(const InputData& x, int force_p);
}
// END MODULE: src/search/candidate_search.hpp
// BEGIN MODULE: src/search/initial_search.hpp
namespace solver {
struct InitialResults {
    ScheduleResult best;
    ScheduleResult probe_base;
    ScheduleResult v5_base;
};
InitialResults refine_initial_candidates(const InputData& x, std::vector<PartitionCandidate>& pcs,
                                         bool serial);
}  // namespace solver
// END MODULE: src/search/initial_search.hpp
// BEGIN MODULE: src/search/layout_bound_search.hpp


namespace solver {
std::vector<ScheduleResult> search_layout_bounds(const InputData& x,
                                                 const std::vector<PartitionCandidate>& placements,
                                                 ScheduleResult& best,
                                                 std::chrono::steady_clock::time_point deadline);
}  // namespace solver
// END MODULE: src/search/layout_bound_search.hpp
// BEGIN MODULE: src/search/list_search.hpp
namespace solver {
ScheduleResult run_v7_list_search(const InputData& x, ScheduleResult best, bool serial,
                                  bool do_list, bool list_deep, bool list_deep_topos,
                                  bool diff_enabled,
                                  std::chrono::steady_clock::time_point main_start,
                                  const std::string& borrow,
                                  std::chrono::steady_clock::time_point deadline =
                                      std::chrono::steady_clock::time_point::max());
}
// END MODULE: src/search/list_search.hpp
// BEGIN MODULE: src/search/placement_search.hpp
namespace solver {
ScheduleResult run_alt_placement(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& v5_base, bool serial,
                                 const std::string& borrow);
}
// END MODULE: src/search/placement_search.hpp
// BEGIN MODULE: src/search/polish_driver.hpp
namespace solver {
void polish_final_schedule(const InputData& x, ScheduleResult& best, bool serial, bool do_wave,
                           std::chrono::steady_clock::time_point main_start, int budget_ms,
                           const std::string& retime_mode, int polish_pass_limit);
}
// END MODULE: src/search/polish_driver.hpp
// BEGIN MODULE: src/search/priority_search.hpp

namespace solver {
void refine_priority_schedules(const InputData& x, const std::vector<ScheduleResult>& seeds,
                               ScheduleResult& best,
                               std::chrono::steady_clock::time_point deadline);
}  // namespace solver
// END MODULE: src/search/priority_search.hpp
// BEGIN MODULE: src/search/wave_search.hpp
namespace solver {
void run_scale_v8_search(const InputData& x, const std::vector<PartitionCandidate>& pcs,
                         const ScheduleResult& v7_incumbent, ScheduleResult& best, bool serial,
                         bool do_wave, std::chrono::steady_clock::time_point main_start,
                         std::chrono::steady_clock::time_point deadline =
                             std::chrono::steady_clock::time_point::max());
}
// END MODULE: src/search/wave_search.hpp
// BEGIN MODULE: src/search/window_borrow.hpp
namespace solver {
ScheduleResult run_window_borrow(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& probe_base, const ScheduleResult& v5_base,
                                 bool serial, const std::string& borrow);
}
// END MODULE: src/search/window_borrow.hpp
namespace solver {
using namespace std;
bool Solver::solve(const InputData& x, const Options& options,
                   chrono::steady_clock::time_point main_start, ScheduleResult& result) const {
    const bool serial = options.mode == SearchMode::kSerial;
    const bool do_list = options.mode == SearchMode::kFull || options.mode == SearchMode::kList;
    const bool list_deep = false, list_deep_topos = false;
    const bool diff_enabled = do_list && !serial;
    const bool do_wave = options.mode == SearchMode::kFull;
    const string borrow = "ac";
    vector<PartitionCandidate> pcs = generate_candidates(x, options.force_p);
    if (pcs.empty()) {
        return false;
    }
    InitialResults initial = refine_initial_candidates(x, pcs, serial);
    ScheduleResult best = move(initial.best);
    ScheduleResult probe_base = move(initial.probe_base);
    ScheduleResult v5_base = move(initial.v5_base);
    best = run_window_borrow(x, move(best), probe_base, v5_base, serial, borrow);
    best = run_boost_borrow(x, move(best), v5_base, serial, borrow);
    best = run_alt_placement(x, move(best), v5_base, serial, borrow);
    const bool small_full_search =
        options.mode == SearchMode::kFull && !serial &&
        x.mb <= search_limits::kExtraLayoutMicrobatchLimit &&
        (i128)x.mb * x.L * operation::kCount <= search_limits::kExtraLayoutNodeLimit &&
        x.L > best.G;
    const auto infinite_deadline = chrono::steady_clock::time_point::max();
    const auto list_deadline =
        small_full_search
            ? main_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.list_deadline_ms)
            : infinite_deadline;
    best = run_v7_list_search(x, move(best), serial, do_list, list_deep, list_deep_topos,
                              diff_enabled, main_start, borrow, list_deadline);
    ScheduleResult v7_incumbent = best;
    const auto wave_deadline =
        small_full_search
            ? main_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.wave_deadline_ms)
            : infinite_deadline;
    run_scale_v8_search(x, pcs, v7_incumbent, best, serial, do_wave, main_start, wave_deadline);
    if (small_full_search) {
        const auto layout_start = chrono::steady_clock::now();
        const auto layout_deadline = min(
            layout_start + chrono::milliseconds(search_limits::kSmallFullSearchBudget.layout_budget_ms),
            main_start + chrono::milliseconds(
                             search_limits::kSmallFullSearchBudget.layout_deadline_cap_ms));
        const i128 layout_anchor = best.time;
        vector<ScheduleResult> layout_seeds;
        if (chrono::steady_clock::now() < layout_deadline) {
            layout_seeds = search_layout_bounds(x, pcs, best, layout_deadline);
        }
        cerr << "LAYOUT_BOUND_STAGE seeds=" << layout_seeds.size()
             << " anchor_Time=" << to_decimal(layout_anchor) << " Time=" << to_decimal(best.time)
             << " elapsed="
             << chrono::duration<double>(chrono::steady_clock::now() - layout_start).count()
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count() << "\n";

        vector<ScheduleResult> priority_seeds;
        priority_seeds.reserve(layout_seeds.size() + 1);
        priority_seeds.push_back(v7_incumbent);
        for (auto& seed : layout_seeds) {
            if (!seed.ops.empty()) {
                priority_seeds.push_back(move(seed));
            }
        }
        const auto priority_start = chrono::steady_clock::now();
        const auto priority_deadline = min(
            priority_start + chrono::milliseconds(
                                 search_limits::kSmallFullSearchBudget.priority_budget_ms),
            main_start + chrono::milliseconds(
                             search_limits::kSmallFullSearchBudget.priority_deadline_cap_ms));
        const i128 priority_anchor = best.time;
        if (chrono::steady_clock::now() < priority_deadline) {
            refine_priority_schedules(x, priority_seeds, best, priority_deadline);
        }
        cerr << "PRIORITY_STAGE seeds=" << priority_seeds.size()
             << " anchor_Time=" << to_decimal(priority_anchor) << " Time=" << to_decimal(best.time)
             << " elapsed="
             << chrono::duration<double>(chrono::steady_clock::now() - priority_start).count()
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count() << "\n";
    }
    polish_final_schedule(x, best, serial, do_wave, main_start, search_limits::kDefaultBudgetMs,
                          options.retime_mode, options.polish_pass_limit);
    result = move(best);
    return true;
}

int run(int argc, char** argv) {
    try {
        auto main_start = chrono::steady_clock::now();
        ios::sync_with_stdio(false);
        cin.tie(nullptr);
        Options options = parse_options(argc, argv);
        if (options.help) {
            cout << "Usage: solver [options] [input-file|-]\n"
                    "Options:\n"
                    "  --mode=full|list|event|serial  Search profile (default: full)\n"
                    "  --force-p=N                   Restrict P; 0 means unrestricted\n"
                    "  --retime-mode=auto|wide       Select retiming arithmetic\n"
                    "  --polish-pass-limit=N         Limit polish passes; 0 means unlimited\n"
                    "  --help, -h                    Show this help\n";
            return 0;
        }
        ifstream input_file;
        istream* input = &cin;
        if (!options.input_path.empty() && options.input_path != "-") {
            input_file.open(options.input_path);
            if (!input_file) {
                throw runtime_error("cannot open input file: " + options.input_path);
            }
            input = &input_file;
        }
        InputData x = read_input(*input);
        ScheduleResult result;
        if (!Solver{}.solve(x, options, main_start, result)) {
            cerr << "no feasible config\n";
            return 2;
        }
        write_output(x, result, options.mode == SearchMode::kSerial);
    } catch (const exception& e) {
        cerr << "input/options error: " << e.what() << "\n";
        return 2;
    }
    return 0;
}

}  // namespace solver
// END MODULE: src/app/solver.cpp
// END TRANSLATION UNIT: src/app/solver.cpp
// BEGIN TRANSLATION UNIT: src/io/numeric.cpp
// BEGIN MODULE: src/io/numeric.cpp
// Exact integer parsing, formatting, and arithmetic helpers.
namespace solver {
using namespace std;
using i128 = __int128_t;
istream& operator>>(istream& in, i128& v) {
    string s;
    if (!(in >> s)) {
        return in;
    }
    v = 0;
    for (char c : s) {
        if (c >= '0' && c <= '9') {
            v = v * 10 + c - '0';
        }
    }
    return in;
}
string to_decimal(i128 x) {
    if (!x) {
        return "0";
    }
    string s;
    while (x) {
        s += char('0' + x % 10);
        x /= 10;
    }
    reverse(s.begin(), s.end());
    return s;
}

}  // namespace solver
// END MODULE: src/io/numeric.cpp
// END TRANSLATION UNIT: src/io/numeric.cpp
// BEGIN TRANSLATION UNIT: src/io/input.cpp
// BEGIN MODULE: src/io/input.cpp
// Input stream parsing into the problem value object.
namespace solver {
using namespace std;
InputData read_input(istream& in) {
    InputData x{};
    if (!(in >> x.N >> x.S >> x.M >> x.Bi >> x.Bo)) {
        throw runtime_error("failed to read input headers (line 1)");
    }
    if (!(in >> x.L >> x.E >> x.Z >> x.Zs >> x.U >> x.Ua >> x.k >> x.mb >> x.Fs >> x.Fio >> x.Fin >>
          x.ax >> x.bx)) {
        throw runtime_error("failed to read input headers (line 2)");
    }
    if (!(in >> x.d >> x.b)) {
        throw runtime_error("failed to read input headers (line 3)");
    }
    x.T.resize(x.L);
    x.load.resize(x.L);
    for (int l = 0; l < x.L; l++) {
        if (!(in >> x.T[l])) {
            throw runtime_error("failed to read T for layer " + to_string(l));
        }
        x.load[l].resize(x.E);
        string line;
        getline(in, line);
        stringstream ss(line);
        vector<i128> a;
        i128 z;
        while (ss >> z) {
            a.push_back(z);
        }
        if ((int)a.size() == x.E) {
            x.load[l] = a;
        } else {
            i128 base = x.T[l] / x.E, rem = x.T[l] % x.E;
            for (int e = 0; e < x.E; e++) {
                x.load[l][e] = base + (e < rem);
            }
        }
    }
    return x;
}
}  // namespace solver
// END MODULE: src/io/input.cpp
// END TRANSLATION UNIT: src/io/input.cpp
// BEGIN TRANSLATION UNIT: src/io/options.cpp
// BEGIN MODULE: src/io/options.cpp

#include <charconv>


namespace solver {
namespace {
int parse_nonnegative(const std::string& value, const std::string& option_name) {
    int parsed = 0;
    const char* begin = value.data();
    const char* end = begin + value.size();
    auto result = std::from_chars(begin, end, parsed);
    if (value.empty() || result.ec != std::errc() || result.ptr != end || parsed < 0) {
        throw std::runtime_error(option_name + " must be a nonnegative integer");
    }
    return parsed;
}
}  // namespace

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            options.help = true;
            return options;
        }
        if (arg == "-") {
            if (!options.input_path.empty()) {
                throw std::runtime_error("multiple input paths");
            }
            options.input_path = arg;
        } else if (arg.rfind("--mode=", 0) == 0) {
            std::string value = arg.substr(7);
            if (value == "full") {
                options.mode = SearchMode::kFull;
            } else if (value == "list") {
                options.mode = SearchMode::kList;
            } else if (value == "event") {
                options.mode = SearchMode::kEvent;
            } else if (value == "serial") {
                options.mode = SearchMode::kSerial;
            } else {
                throw std::runtime_error("--mode must be full, list, event, or serial");
            }
        } else if (arg.rfind("--force-p=", 0) == 0) {
            options.force_p = parse_nonnegative(arg.substr(10), "--force-p");
        } else if (arg.rfind("--retime-mode=", 0) == 0) {
            options.retime_mode = arg.substr(14);
            if (options.retime_mode != "auto" && options.retime_mode != "wide") {
                throw std::runtime_error("--retime-mode must be auto or wide");
            }
        } else if (arg.rfind("--polish-pass-limit=", 0) == 0) {
            options.polish_pass_limit = parse_nonnegative(arg.substr(20), "--polish-pass-limit");
        } else if (!arg.empty() && arg[0] != '-') {
            if (!options.input_path.empty()) {
                throw std::runtime_error("multiple input paths");
            }
            options.input_path = arg;
        } else {
            throw std::runtime_error("unknown option: " + arg + " (use --help)");
        }
    }
    return options;
}

}  // namespace solver
// END MODULE: src/io/options.cpp
// END TRANSLATION UNIT: src/io/options.cpp
// BEGIN TRANSLATION UNIT: src/io/output.cpp
// BEGIN MODULE: src/io/output.cpp
// Stable result and schedule serialization.
// BEGIN MODULE: src/placement/expert_mapping.hpp
namespace solver {
std::vector<std::vector<int>> build_expert_map(const InputData& x, int P, i128& cost);
std::vector<std::array<i128, operation::kCount>> compute_durations(const InputData& x,
                                                                   const Candidate& c);
}  // namespace solver
// END MODULE: src/placement/expert_mapping.hpp
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
// END MODULE: src/io/output.cpp
// END TRANSLATION UNIT: src/io/output.cpp
// BEGIN TRANSLATION UNIT: src/placement/expert_mapping.cpp
// BEGIN MODULE: src/placement/expert_mapping.cpp
// Per-layer expert assignment and duration cost model.
namespace solver {
using namespace std;
vector<vector<int>> build_expert_map(const InputData& x, int P, i128& cost) {
    vector<vector<int>> mp(x.L, vector<int>(x.E));
    cost = 0;
    for (int l = 0; l < x.L; l++) {
        vector<int> e(x.E);
        iota(e.begin(), e.end(), 0);
        sort(e.begin(), e.end(), [&](int a, int b) { return x.load[l][a] > x.load[l][b]; });
        vector<i128> loads(P);
        vector<int> cnt(P);
        for (int id : e) {
            int r = -1;
            for (int j = 0; j < P; j++) {
                if (cnt[j] < x.E / P && (r < 0 || loads[j] < loads[r])) {
                    r = j;
                }
            }
            mp[l][id] = r;
            ++cnt[r];
            loads[r] += x.load[l][id];
        }
        i128 total = 0, heavy = 0, sq = 0;
        for (auto v : x.load[l]) {
            total += v;
            heavy = max(heavy, v);
        }
        for (auto v : loads) {
            sq += v * v;
        }
        for (int it = 0; it < 6; it++) {
            i128 mx = *max_element(loads.begin(), loads.end());
            if (mx == max(heavy, ceil_div(total, P))) {
                break;
            }
            vector<int> order(P);
            iota(order.begin(), order.end(), 0);
            sort(order.begin(), order.end(), [&](int a, int b) { return loads[a] > loads[b]; });
            int be = -1, bf = -1;
            i128 bm = mx, bs = sq;
            for (int a = 0; a < x.E; a++) {
                for (int b = a + 1; b < x.E; b++) {
                    int ra = mp[l][a], rb = mp[l][b];
                    if (ra == rb) {
                        continue;
                    }
                    i128 na = loads[ra] - x.load[l][a] + x.load[l][b],
                         nb = loads[rb] - x.load[l][b] + x.load[l][a], outside = 0;
                    for (int r : order) {
                        if (r != ra && r != rb) {
                            outside = loads[r];
                            break;
                        }
                    }
                    i128 nm = max(outside, max(na, nb)),
                         ns =
                             sq - loads[ra] * loads[ra] - loads[rb] * loads[rb] + na * na + nb * nb;
                    if (nm < bm || (nm == bm && ns < bs)) {
                        bm = nm;
                        bs = ns;
                        be = a;
                        bf = b;
                    }
                }
            }
            if (be < 0) {
                break;
            }
            int ra = mp[l][be], rb = mp[l][bf];
            loads[ra] = loads[ra] - x.load[l][be] + x.load[l][bf];
            loads[rb] = loads[rb] - x.load[l][bf] + x.load[l][be];
            swap(mp[l][be], mp[l][bf]);
            sq = bs;
        }
        cost += *max_element(loads.begin(), loads.end());
    }
    return mp;
}
vector<array<i128, operation::kCount>> compute_durations(const InputData& x, const Candidate& c) {
    vector<array<i128, operation::kCount>> d(x.L);
    i128 H = x.d * x.b / x.k;
    for (int l = 0; l < x.L; l++) {
        vector<i128> load(c.P);
        for (int e = 0; e < x.E; e++) {
            load[c.map[l][e]] += x.load[l][e];
        }
        i128 m = *max_element(load.begin(), load.end()), X = ceil_div(x.T[l] * H, c.P),
             pin = min(c.P, x.S) - 1, pout = c.P - 1 - pin;
        i128 com = max(ceil_div(pin * X, x.Bi), ceil_div(pout * X, x.Bo)) * x.Fio, g = m * x.Fin,
             s = x.T[l] * x.Fs;
        d[l] = {};
        d[l][operation::kSharedForward] = s;
        d[l][operation::kDispatchForward] = com;
        d[l][operation::kExpertForward] = g;
        d[l][operation::kCombineForward] = com;
        d[l][operation::kSharedBackward] = ceil_div(x.ax * s, search_limits::kMillion);
        d[l][operation::kCombineBackward] = ceil_div(x.ax * com, search_limits::kMillion);
        d[l][operation::kExpertInputGradient] = ceil_div(x.ax * g, search_limits::kMillion);
        d[l][operation::kExpertWeightGradient] =
            ceil_div(x.ax * x.bx * g, search_limits::kTrillion);
        d[l][operation::kDispatchBackward] = ceil_div(x.ax * com, search_limits::kMillion);
        d[l][operation::kSharedWeightGradient] =
            ceil_div(x.ax * x.bx * s, search_limits::kTrillion);
    }
    return d;
}
}  // namespace solver
// END MODULE: src/placement/expert_mapping.cpp
// END TRANSLATION UNIT: src/placement/expert_mapping.cpp
// BEGIN TRANSLATION UNIT: src/placement/grouped_placement.cpp
// BEGIN MODULE: src/placement/grouped_placement.cpp
// BEGIN MODULE: src/placement/grouped_placement.hpp
namespace grouped_placement {
using i128 = __int128_t;
namespace limits {
inline constexpr int kMaxWeightTypes = 4;
inline constexpr int kMaxRanks = 32;
inline constexpr int kMaxSlotsPerRank = 32;
inline constexpr std::uint64_t kDefaultNodeBudget = 250000;
}  // namespace limits
struct Plan {
    std::vector<i128> values;
    std::vector<std::vector<int>> rank_counts;
    i128 peak = 0;
};
bool find_at_peak(const std::vector<i128>& slots, int P, int per_rank, i128 target_peak, Plan& plan,
                  std::uint64_t node_budget = limits::kDefaultNodeBudget);
bool materialize(const std::vector<i128>& slots, const Plan& plan, std::vector<int>& row);
}  // namespace grouped_placement
// END MODULE: src/placement/grouped_placement.hpp

// ===== grouped_placement =====

// Bounded exact placement search for layers with only a few distinct slot
// weights. Experts with equal weights are grouped; the search assigns counts
// of each weight to ranks, then materialize() maps those counts back to the
// original expert indices.

namespace grouped_placement {
using i128 = __int128_t;
namespace detail {
struct State {
    int rank;
    int first_pattern;
    std::vector<int> used;

    bool operator==(const State& other) const {
        return rank == other.rank && first_pattern == other.first_pattern && used == other.used;
    }
};

struct StateHash {
    std::size_t operator()(const State& state) const {
        std::size_t h = std::hash<int>{}(state.rank);
        auto mix = [&h](std::size_t x) { h ^= x + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2); };
        mix(std::hash<int>{}(state.first_pattern));
        for (int x : state.used) {
            mix(std::hash<int>{}(x));
        }
        return h;
    }
};

class Search {
private:
    int P;
    int per_rank;
    i128 target;
    const std::vector<i128>& values;
    const std::vector<int>& available;
    std::uint64_t budget;
    std::uint64_t visited = 0;
    bool exhausted = false;
    std::vector<std::vector<int>> patterns;
    std::vector<std::vector<int>> solution;
    std::unordered_set<State, StateHash> failed;

public:
    Search(int p, int q, i128 cap, const std::vector<i128>& type_values,
           const std::vector<int>& type_counts, std::uint64_t node_budget)
        : P(p),
          per_rank(q),
          target(cap),
          values(type_values),
          available(type_counts),
          budget(node_budget) {}

    bool solve() {
        std::vector<int> pattern(values.size(), 0);
        enumerate_patterns(0, per_rank, 0, pattern);
        if (exhausted || patterns.empty()) {
            return false;
        }
        std::vector<int> used(values.size(), 0);
        std::vector<std::vector<int>> chosen;
        chosen.reserve(P);
        return dfs(0, 0, used, chosen) && !exhausted;
    }

    bool is_exhausted() const {
        return exhausted;
    }

    std::vector<std::vector<int>> take_solution() {
        return std::move(solution);
    }

private:
    bool tick() {
        if (++visited > budget) {
            exhausted = true;
            return false;
        }
        return true;
    }

    void enumerate_patterns(int type, int slots_left, i128 load, std::vector<int>& counts) {
        if (exhausted || !tick()) {
            return;
        }
        if (type == static_cast<int>(values.size()) - 1) {
            int n = slots_left;
            if (n < 0 || n > available[type]) {
                return;
            }
            i128 sum = load + static_cast<i128>(n) * values[type];
            if (sum > target) {
                return;
            }
            counts[type] = n;
            patterns.push_back(counts);
            return;
        }
        const int max_n = std::min(slots_left, available[type]);
        for (int n = 0; n <= max_n && !exhausted; ++n) {
            i128 next_load = load + static_cast<i128>(n) * values[type];
            if (next_load > target) {
                break;
            }
            counts[type] = n;
            enumerate_patterns(type + 1, slots_left - n, next_load, counts);
        }
    }

    bool dfs(int rank, int first_pattern, std::vector<int>& used,
             std::vector<std::vector<int>>& chosen) {
        if (!tick()) {
            return false;
        }
        if (rank == P) {
            if (used == available) {
                solution = chosen;
                return true;
            }
            return false;
        }

        State key{rank, first_pattern, used};
        if (failed.find(key) != failed.end()) {
            return false;
        }
        const int remaining_ranks = P - rank - 1;
        for (int p = first_pattern; p < static_cast<int>(patterns.size()); ++p) {
            const auto& pattern = patterns[p];
            bool fits = true;
            for (std::size_t t = 0; t < used.size(); ++t) {
                if (used[t] + pattern[t] > available[t]) {
                    fits = false;
                    break;
                }
                // After this rank, remaining experts of this type must still
                // fit in the remaining rank capacities.
                if (available[t] - used[t] - pattern[t] > remaining_ranks * per_rank) {
                    fits = false;
                    break;
                }
            }
            if (!fits) {
                continue;
            }
            for (std::size_t t = 0; t < used.size(); ++t) {
                used[t] += pattern[t];
            }
            chosen.push_back(pattern);
            if (dfs(rank + 1, p, used, chosen)) {
                return true;
            }
            chosen.pop_back();
            for (std::size_t t = 0; t < used.size(); ++t) {
                used[t] -= pattern[t];
            }
            if (exhausted) {
                return false;
            }
        }
        failed.insert(std::move(key));
        return false;
    }
};
}  // namespace detail

// Find a rank-by-weight allocation under target_peak. Returns false when the
// target is infeasible, the type count is outside the supported small range,
// or the bounded search exhausts its node budget. It never mutates input.
// Search is bounded to <=4 weight types, P<=32, per_rank<=32 and the supplied
// node budget. For other shapes, retain the caller's existing MAP.
bool find_at_peak(const std::vector<i128>& slots, int P, int per_rank, i128 target_peak,
                         Plan& out, std::uint64_t node_budget) {
    if (P < 1 || P > limits::kMaxRanks || per_rank < 1 || per_rank > limits::kMaxSlotsPerRank ||
        slots.size() != static_cast<std::size_t>(P) * per_rank || target_peak < 0 ||
        node_budget == 0) {
        return false;
    }

    std::vector<i128> values = slots;
    if (std::any_of(values.begin(), values.end(), [](i128 x) { return x < 0; })) {
        return false;
    }
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
    if (values.empty() || values.size() > limits::kMaxWeightTypes) {
        return false;
    }

    std::vector<int> available(values.size(), 0);
    for (i128 x : slots) {
        int t =
            static_cast<int>(std::lower_bound(values.begin(), values.end(), x) - values.begin());
        ++available[t];
    }

    detail::Search search(P, per_rank, target_peak, values, available, node_budget);
    if (!search.solve()) {
        return false;
    }

    Plan result;
    result.values = std::move(values);
    result.rank_counts = search.take_solution();
    result.peak = target_peak;
    out = std::move(result);
    return true;
}

// Convert a cached type-count plan back to expert-index ranks for this layer.
// This explicitly re-buckets the current slots, so plans can safely be reused
// across layers with the same value histogram but different expert ordering.
bool materialize(const std::vector<i128>& slots, const Plan& plan, std::vector<int>& row) {
    const int P = static_cast<int>(plan.rank_counts.size());
    if (P < 1 || plan.values.empty() || plan.values.size() > limits::kMaxWeightTypes) {
        return false;
    }
    const std::size_t K = plan.values.size();
    std::vector<std::vector<int>> experts(K);
    for (int e = 0; e < static_cast<int>(slots.size()); ++e) {
        auto it = std::lower_bound(plan.values.begin(), plan.values.end(), slots[e]);
        if (it == plan.values.end() || *it != slots[e]) {
            return false;
        }
        experts[static_cast<std::size_t>(it - plan.values.begin())].push_back(e);
    }
    std::vector<int> expected(K, 0);
    for (const auto& rank : plan.rank_counts) {
        if (rank.size() != K) {
            return false;
        }
        for (std::size_t t = 0; t < K; ++t) {
            if (rank[t] < 0) {
                return false;
            }
            expected[t] += rank[t];
        }
    }
    for (std::size_t t = 0; t < K; ++t) {
        if (expected[t] != static_cast<int>(experts[t].size())) {
            return false;
        }
    }

    std::vector<int> result(slots.size(), -1);
    std::vector<std::size_t> cursor(K, 0);
    for (int r = 0; r < P; ++r) {
        int rank_size = 0;
        for (std::size_t t = 0; t < K; ++t) {
            rank_size += plan.rank_counts[r][t];
            for (int n = 0; n < plan.rank_counts[r][t]; ++n) {
                if (cursor[t] >= experts[t].size()) {
                    return false;
                }
                result[experts[t][cursor[t]++]] = r;
            }
        }
        if (rank_size != static_cast<int>(slots.size() / P)) {
            return false;
        }
    }
    if (std::any_of(result.begin(), result.end(), [](int r) { return r < 0; })) {
        return false;
    }
    row = std::move(result);
    return true;
}

}  // namespace grouped_placement
// END MODULE: src/placement/grouped_placement.cpp
// END TRANSLATION UNIT: src/placement/grouped_placement.cpp
// BEGIN TRANSLATION UNIT: src/scheduling/event_scheduler.cpp
// BEGIN MODULE: src/scheduling/event_scheduler.cpp
// BEGIN MODULE: src/scheduling/event_scheduler.hpp
namespace event_sched {
namespace limits {
inline constexpr int kReadyLookahead = 16;
inline constexpr int kEventCompletion = 0;
inline constexpr int kReservationReturn = 1;
}  // namespace limits
using i128 = __int128_t;
bool schedule(int mb, int L, int G, const std::vector<int>& layer_group,
              const std::vector<std::array<i128, operation::kCount>>& dur,
              const std::vector<int>& group_layers, const std::vector<int>& activation_capacity,
              const std::vector<int>& comm_buffers, int window, std::vector<Op>& out,
              i128& makespan, int mode = 0, int fill_groups = 0, int fill_mbs = 0,
              int reward_tenths = 0, bool flat_reward = false, int window_release = 0);
}  // namespace event_sched
// END MODULE: src/scheduling/event_scheduler.hpp

// BEGIN MODULE: src/core/operation_graph.hpp

// The shared ten-operation DAG. Keep edge emission order stable: adjacency
// order participates in deterministic ready and topological tie handling.
namespace operation_graph {
inline constexpr int kLayerStride = operation::kCount;

constexpr int node_id(int microbatch, int layer, int op, int layer_count) {
    return (microbatch * layer_count + layer) * operation::kCount + op;
}

constexpr int layer_of(int id, int layer_count) {
    return (id / operation::kCount) % layer_count;
}

constexpr int operation_of(int id) {
    return id % operation::kCount;
}

constexpr void decode_node(int id, int layer_count, int& microbatch, int& layer, int& op) {
    const int layer_stride = layer_count * operation::kCount;
    microbatch = id / layer_stride;
    const int in_microbatch = id % layer_stride;
    layer = in_microbatch / operation::kCount;
    op = in_microbatch % operation::kCount;
}

template <class Id, class Edge>
inline void append_layer_edges(int microbatch, int layer, int layer_count, Id id, Edge edge) {
    const int base = id(microbatch, layer, operation::kSharedForward);
    edge(base + operation::kDispatchForward, base + operation::kExpertForward);
    edge(base + operation::kExpertForward, base + operation::kCombineForward);
    edge(base + operation::kSharedForward, base + operation::kCombineForward);
    edge(base + operation::kCombineForward, base + operation::kSharedBackward);
    edge(base + operation::kCombineForward, base + operation::kCombineBackward);
    edge(base + operation::kCombineBackward, base + operation::kExpertInputGradient);
    edge(base + operation::kCombineBackward, base + operation::kExpertWeightGradient);
    edge(base + operation::kCombineBackward, base + operation::kSharedWeightGradient);
    edge(base + operation::kExpertInputGradient, base + operation::kDispatchBackward);
    edge(base + operation::kSharedBackward, base + operation::kDispatchBackward);
    if (layer > 0) {
        const int previous = id(microbatch, layer - 1, operation::kSharedForward);
        edge(previous + operation::kCombineForward, base + operation::kSharedForward);
        edge(previous + operation::kCombineForward, base + operation::kDispatchForward);
    }
    if (layer + 1 < layer_count) {
        const int next = id(microbatch, layer + 1, operation::kSharedForward);
        edge(next + operation::kDispatchBackward, base + operation::kSharedBackward);
        edge(next + operation::kDispatchBackward, base + operation::kCombineBackward);
    }
}
}  // namespace operation_graph
// END MODULE: src/core/operation_graph.hpp
// BEGIN MODULE: src/scheduling/schedule_api.hpp

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
// END MODULE: src/scheduling/schedule_api.hpp

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
              const std::vector<int>& group_layers, const std::vector<int>& activation_capacity,
              const std::vector<int>& comm_buffers, int window, std::vector<Op>& out,
              i128& makespan, int mode, int fill_groups, int fill_mbs, int reward_tenths,
              bool flat_reward, int window_release) {
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

namespace scheduling {
bool EventScheduleStrategy::schedule(const ProblemView& problem, const EventConfig& config,
                                     ScheduleOutput& output) {
    if (!config.activation_capacity || !config.communication_buffers) {
        return false;
    }
    return event_sched::schedule(
        problem.mb, problem.layers, problem.groups, problem.layer_group, problem.durations,
        problem.group_layers, *config.activation_capacity, *config.communication_buffers,
        config.window, output.operations, output.makespan, config.mode, config.fill_groups,
        config.fill_microbatches, config.reward_tenths, config.flat_reward, config.window_release);
}
}  // namespace scheduling
// END MODULE: src/scheduling/event_scheduler.cpp
// END TRANSLATION UNIT: src/scheduling/event_scheduler.cpp
// BEGIN TRANSLATION UNIT: src/scheduling/list_scheduler.cpp
// BEGIN MODULE: src/scheduling/list_scheduler.cpp
// BEGIN MODULE: src/scheduling/list_scheduler.hpp
namespace list_sched {
namespace limits {
inline constexpr int kVariantCount = 8;
}
using i128 = __int128_t;
using Op = solver::ScheduledOperation;
using Dur = std::vector<std::array<i128, operation::kCount>>;
inline bool comm(int o) {
    return o == operation::kDispatchForward || o == operation::kCombineForward ||
           o == operation::kCombineBackward || o == operation::kDispatchBackward;
}
bool schedule(int mb, int L, int G, const std::vector<int>& grp, const Dur& d,
              const std::vector<int>& ng, int W, int vi, bool early, int gap, int fs, int fm,
              i128 busy, int ratio10, bool ramp, std::vector<Op>& out, i128& tm,
              std::vector<i128>* starts = nullptr, std::vector<i128>* ends = nullptr,
              bool wave_rank = false, bool fill_gaps = false, int rank_mode = 0, int A = 1,
              int B = 1, int phase = 0, int pitch_num = 1, int pitch_den = 1, int duration_head = 0,
              bool mb_desc = false, int dw_order = 0, std::uint64_t random_seed = 0,
              int random_jitter_span = 1, int random_wave_stride = 1,
              const std::vector<i128>* microbatch_offset_ticks = nullptr,
              int microbatch_offset_denominator = 1);
}  // namespace list_sched
// END MODULE: src/scheduling/list_scheduler.hpp


// ===== list_scheduler =====
namespace list_sched {
namespace {
constexpr int kRankModeWave = static_cast<int>(scheduling::ListRankMode::kWavefront);
constexpr int kRankModeDagPitch = static_cast<int>(scheduling::ListRankMode::kDagPitch);
constexpr int kRankModeRandomKey = static_cast<int>(scheduling::ListRankMode::kRandomKey);
constexpr int kRankModeNonuniformOffsets =
    static_cast<int>(scheduling::ListRankMode::kNonuniformMicrobatchOffsets);

std::uint64_t splitmix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}
}  // namespace

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
              int duration_head, bool mb_desc, int dw_order, std::uint64_t random_seed,
              int random_jitter_span, int random_wave_stride,
              const std::vector<i128>* microbatch_offset_ticks,
              int microbatch_offset_denominator) {
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
    if (rank_mode == kRankModeDagPitch || rank_mode == kRankModeNonuniformOffsets) {
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
    if (rank_mode == kRankModeNonuniformOffsets &&
        (!microbatch_offset_ticks ||
         static_cast<int>(microbatch_offset_ticks->size()) != mb ||
         microbatch_offset_denominator <= 0)) {
        return false;
    }
    if (rank_mode == kRankModeNonuniformOffsets) {
        for (int m = 0; m < mb; ++m) {
            if ((*microbatch_offset_ticks)[m] < 0 ||
                (m > 0 && (*microbatch_offset_ticks)[m] < (*microbatch_offset_ticks)[m - 1])) {
                return false;
            }
        }
    }
    if (rank_mode == kRankModeRandomKey &&
        (random_jitter_span <= 0 || random_wave_stride < 0)) {
        return false;
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
        if (rank_mode == kRankModeWave) {
            i128 forward = (i128)A * m +
                           (i128)B * (o < operation::kSharedBackward ? l : 2 * L - l) +
                           (o >= operation::kSharedBackward ? (i128)phase * L / 2 : 0);
            return std::array<i128, 4>{
                (o == operation::kExpertWeightGradient || o == operation::kSharedWeightGradient)
                    ? 1
                    : 0,
                forward, dw, o};
        }
        if (rank_mode == kRankModeDagPitch) {
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
        if (rank_mode == kRankModeRandomKey) {
            const std::uint64_t key = splitmix64(
                random_seed ^ (static_cast<std::uint64_t>(x) * 0x9e3779b97f4a7c15ULL));
            const i128 jitter = static_cast<i128>(key %
                static_cast<std::uint64_t>(random_jitter_span));
            const i128 layer_wave =
                o < operation::kSharedBackward ? l : (2 * L - l);
            const i128 topo = static_cast<i128>(m) * (2 * L) + layer_wave;
            const bool is_weight_gradient =
                o == operation::kExpertWeightGradient ||
                o == operation::kSharedWeightGradient;
            const i128 gradient_class =
                (dw_order == 2) == is_weight_gradient ? 1 : 0;
            return std::array<i128, 4>{
                gradient_class,
                topo * random_wave_stride + jitter,
                static_cast<i128>(key), o};
        }
        if (rank_mode == kRankModeNonuniformOffsets) {
            const i128 topology = duration_head == 1
                                      ? h[x]
                                      : (duration_head == 2
                                             ? h_finish[x]
                                             : layer_prefix[l] + (d[l][o] + 9) / 10);
            const i128 offset = (*microbatch_offset_ticks)[m] * max_work * pitch_num /
                                microbatch_offset_denominator;
            const i128 backward_phase =
                o >= operation::kSharedBackward ? (i128)phase * max_work * pitch_num : 0;
            return std::array<i128, 4>{
                (o == operation::kExpertWeightGradient ||
                 o == operation::kSharedWeightGradient)
                    ? 1
                    : 0,
                offset + topology * pitch_den + backward_phase, dw, o};
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
        config.fill_gaps,
        config.priority_mode == ListRankMode::kLegacy
            ? config.rank_mode
            : static_cast<int>(config.priority_mode),
        config.rank_a, config.rank_b, config.phase,
        config.pitch_numerator, config.pitch_denominator, config.duration_head,
        config.microbatch_descending, config.weight_gradient_order, config.random_seed,
        config.random_jitter_span, config.random_wave_stride,
        config.microbatch_offset_ticks.empty() ? nullptr : &config.microbatch_offset_ticks,
        config.microbatch_offset_denominator);
}
}  // namespace scheduling
// END MODULE: src/scheduling/list_scheduler.cpp
// END TRANSLATION UNIT: src/scheduling/list_scheduler.cpp
// BEGIN TRANSLATION UNIT: src/search/schedule_validation.cpp
// BEGIN MODULE: src/search/schedule_validation.cpp
// BEGIN MODULE: src/search/schedule_validation.hpp

namespace solver {
bool is_feasible_schedule(const InputData& x, const ScheduleResult& schedule);
}  // namespace solver
// END MODULE: src/search/schedule_validation.hpp


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
// END MODULE: src/search/schedule_validation.cpp
// END TRANSLATION UNIT: src/search/schedule_validation.cpp
// BEGIN TRANSLATION UNIT: src/search/candidate_search.cpp
// BEGIN MODULE: src/search/candidate_search.cpp
// Partition generation and dynamic-programming initialization.
namespace solver {
using namespace std;
vector<PartitionCandidate> generate_candidates(const InputData& x, int force_p) {
    int R = x.N * x.S;
    i128 H = x.d * x.b / x.k;
    vector<PartitionCandidate> pcs;
    for (int P = 1; P <= min(R, x.E); P++) {
        if ((force_p && P != force_p) || x.E % P || (x.S % P && P % x.S)) {
            continue;
        }
        i128 mapcost;
        auto mp = build_expert_map(x, P, mapcost);
        i128 q = (x.E / P) * x.Z + x.Zs;
        bool zero_comms = true;
        vector<i128> pref(x.L + 1);
        for (int l = 0; l < x.L; l++) {
            i128 X = ceil_div(x.T[l] * H, P), pin = min(P, x.S) - 1, pout = P - 1 - pin;
            i128 com = max(ceil_div(pin * X, x.Bi), ceil_div(pout * X, x.Bo)) * x.Fio,
                 g = ceil_div(x.T[l], P) * x.Fin, s = x.T[l] * x.Fs;
            if (com) {
                zero_comms = false;
            }
            pref[l + 1] = pref[l] + 4 * com + 2 * g + 2 * s +
                          2 * ceil_div(x.ax * com, search_limits::kMillion) +
                          ceil_div(x.ax * g, search_limits::kMillion) +
                          ceil_div(x.ax * x.bx * g, search_limits::kTrillion) +
                          ceil_div(x.ax * s, search_limits::kMillion) +
                          ceil_div(x.ax * x.bx * s, search_limits::kTrillion);
        }
        PartitionCandidate pc;
        i128 best_score = search_limits::kInfiniteTime;
        int vmax = min({x.L, search_limits::kMaximumPartitionCount, R / P});
        for (int V = 1; V <= vmax; V++) {
            i128 INF = search_limits::kInfiniteTime;
            vector<vector<i128>> dp(V + 1, vector<i128>(x.L + 1, INF));
            vector<vector<int>> par(V + 1, vector<int>(x.L + 1, -1));
            dp[0][0] = 0;
            for (int j = 1; j <= V; j++) {
                for (int i = j; i <= x.L - (V - j); i++) {
                    for (int h = j - 1; h < i; h++) {
                        if (dp[j - 1][h] < INF &&
                            (i - h) * (q + x.Ua) + (zero_comms ? 0 : x.U) <= x.M) {
                            i128 val = max(dp[j - 1][h], pref[i] - pref[h]);
                            if (val < dp[j][i]) {
                                dp[j][i] = val, par[j][i] = h;
                            }
                        }
                    }
                }
            }
            if (dp[V][x.L] >= INF) {
                continue;
            }
            Candidate c;
            c.P = P;
            c.V = V;
            c.score = dp[V][x.L] * search_limits::kMillion + mapcost;
            c.map = mp;
            c.cuts.resize(V + 1);
            c.cuts[V] = x.L;
            int at = x.L;
            bool ok = true;
            for (int j = V; j > 0; j--) {
                int h = par[j][at];
                if (h < 0) {
                    ok = false;
                    break;
                }
                c.cuts[j - 1] = h;
                at = h;
            }
            if (!ok) {
                continue;
            }
            if (c.score < best_score) {
                best_score = c.score;
                pc.best_v = c;
            }
            pc.max_v = c;
        }
        if (pc.max_v.P) {
            pcs.push_back(move(pc));
        }
    }
    return pcs;
}

}  // namespace solver
// END MODULE: src/search/candidate_search.cpp
// END TRANSLATION UNIT: src/search/candidate_search.cpp
// BEGIN TRANSLATION UNIT: src/search/layout_search.cpp
// BEGIN MODULE: src/search/layout_search.cpp
// BEGIN MODULE: src/search/layout_search.hpp
namespace solver {
ScheduleResult evaluate_layouts(
    const InputData& x, const Candidate& c, bool rich, bool deep,
    std::chrono::steady_clock::time_point deadline = std::chrono::steady_clock::time_point::max());
}
// END MODULE: src/search/layout_search.hpp
// Evaluate group layouts under the event scheduler.
namespace solver {
using namespace std;
ScheduleResult evaluate_layouts(const InputData& x, const Candidate& c, bool rich, bool deep,
                                chrono::steady_clock::time_point deadline) {
    ScheduleResult best;
    best.c = c;
    auto dur = compute_durations(x, c);
    vector<int> base_group(x.L);
    for (int g = 0; g < c.V; g++) {
        for (int l = c.cuts[g]; l < c.cuts[g + 1]; l++) {
            base_group[l] = g;
        }
    }
    auto test_layout = [&](const vector<int>& lg, const vector<int>& cuts, int K, int G) {
        if (chrono::steady_clock::now() >= deadline) {
            return;
        }
        vector<int> ng(G);
        for (int g : lg) {
            ng[g]++;
        }
        vector<int> windows = rich ? vector<int>{1, 2, G, 2 * G, 0} : vector<int>{0};
        sort(windows.begin(), windows.end());
        windows.erase(unique(windows.begin(), windows.end()), windows.end());
        for (int one = 0; one <= (rich ? 1 : 0); one++) {
            vector<int> caps(G), buf(G);
            bool ok = true;
            for (int g = 0; g < G; g++) {
                bool zero = true;
                for (int l = 0; l < x.L; l++) {
                    if (lg[l] == g && (dur[l][operation::index(operation::kDispatchForward)] ||
                                       dur[l][operation::index(operation::kCombineForward)] ||
                                       dur[l][operation::index(operation::kCombineBackward)] ||
                                       dur[l][operation::index(operation::kDispatchBackward)])) {
                        zero = false;
                    }
                }
                // If every communication duration is zero, the official checker omits buffers.
                int bbuf = zero ? 0 : 1;
                if (rich && !one && !zero) {
                    i128 two = x.M - ng[g] * ((x.E / c.P) * x.Z + x.Zs) - 2 * x.U;
                    if (two >= 0 && two / x.Ua >= ng[g]) {
                        bbuf = 2;
                    }
                }
                i128 avail = x.M - ng[g] * ((x.E / c.P) * x.Z + x.Zs) - (zero ? 0 : bbuf * x.U);
                if (avail < 0) {
                    ok = false;
                    break;
                }
                caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                buf[g] = bbuf;
                if (caps[g] < ng[g]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) {
                continue;
            }
            int mmax = rich ? 2 : 0;
            for (int mode = 0; mode <= mmax; mode++) {
                for (int w : windows) {
                    if (chrono::steady_clock::now() >= deadline) {
                        return;
                    }
                    vector<event_sched::Op> ops;
                    i128 tm;
                    scheduling::ProblemView problem{x.mb, x.L, G, lg, dur, ng};
                    scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                    scheduling::EventConfig config;
                    config.activation_capacity = &caps;
                    config.communication_buffers = &buf;
                    config.window = w;
                    config.mode = mode;
                    scheduling::ScheduleOutput output{ops, tm};
                    if (scheduler.run(config, output) && tm < best.time) {
                        best.time = tm;
                        best.G = G;
                        best.K = K;
                        best.cuts = cuts;
                        best.group = lg;
                        best.ops.swap(ops);
                    }
                }
            }
        }
    };
    test_layout(base_group, c.cuts, c.V, c.V);
    if (rich && deep) {
        int max_g = min(x.L / 2, x.N * x.S / c.P);
        set<int> gs;
        for (int g : {max_g, min(max_g, c.V), max(1, min(max_g, c.V / 2))}) {
            if (g >= 1 && g <= max_g) {
                gs.insert(g);
            }
        }
        for (int G : gs) {
            if (chrono::steady_clock::now() >= deadline) {
                break;
            }
            int K = 2 * G;
            vector<int> cuts(K + 1), group(x.L);
            for (int j = 0; j <= K; j++) {
                cuts[j] = x.L * j / K;
            }
            for (int j = 0; j < K; j++) {
                for (int l = cuts[j]; l < cuts[j + 1]; l++) {
                    group[l] = (j < G ? j : 2 * G - 1 - j);
                }
            }
            test_layout(group, cuts, K, G);
        }
        if (best.time < search_limits::kInfiniteTime) {
            vector<i128> lw(x.L);
            for (int l = 0; l < x.L; l++) {
                for (auto v : dur[l]) {
                    lw[l] += v;
                }
            }
            vector<int> order;
            for (int j = 1; j < best.K; j++) {
                if (best.cuts[j] > 0 && best.cuts[j] < x.L) {
                    order.push_back(j);
                }
            }
            sort(order.begin(), order.end(), [&](int a, int b) {
                return abs((long long)(lw[best.cuts[a] - 1] - lw[best.cuts[a]])) >
                       abs((long long)(lw[best.cuts[b] - 1] - lw[best.cuts[b]]));
            });
            vector<int> seed = best.cuts;
            int K = best.K, G = best.G;
            int tried = 0;
            for (int j : order) {
                if (chrono::steady_clock::now() >= deadline) {
                    break;
                }
                for (int delta : {-1, 1}) {
                    if (chrono::steady_clock::now() >= deadline) {
                        break;
                    }
                    auto cuts = seed;
                    cuts[j] += delta;
                    bool ok = true;
                    for (int z = 1; z < K; z++) {
                        if (cuts[z] <= cuts[z - 1] || cuts[z] >= cuts[z + 1]) {
                            ok = false;
                        }
                    }
                    if (!ok) {
                        continue;
                    }
                    vector<int> group(x.L);
                    for (int bl = 0; bl < K; bl++) {
                        int g = (K == G ? bl : (bl < G ? bl : 2 * G - 1 - bl));
                        for (int l = cuts[bl]; l < cuts[bl + 1]; l++) {
                            group[l] = g;
                        }
                    }
                    test_layout(group, cuts, K, G);
                }
                if (++tried >= 3) {
                    break;
                }
            }
        }
    }
    if (best.time >= search_limits::kInfiniteTime) {
        best.G = c.V;
        best.K = c.V;
        best.cuts = c.cuts;
        best.group = base_group;
        best.time = 0;
        for (int mb = 0; mb < x.mb; mb++) {
            for (int l = 0; l < x.L; l++) {
                for (auto d : dur[l]) {
                    best.time += d + 1;
                }
            }
        }
    }
    return best;
}

}  // namespace solver
// END MODULE: src/search/layout_search.cpp
// END TRANSLATION UNIT: src/search/layout_search.cpp
// BEGIN TRANSLATION UNIT: src/search/layout_bound_search.cpp
// BEGIN MODULE: src/search/layout_bound_search.cpp


namespace solver {
namespace {
using namespace std;
using Clock = chrono::steady_clock;
using i128 = __int128_t;
constexpr i128 kInf = search_limits::kInfiniteTime;
constexpr int kConstraintThresholds = 7;
constexpr int kSeedLimit = 8;
constexpr int kMaxLayoutsPerPlacement = 12;
constexpr size_t kMaxFoldCacheEntries = 1'000'000;

struct ResourceConstraint {
    i128 release = 0;
    i128 tail = 0;
    int engine = 0;
    vector<i128> prefix;
};

struct LayoutSeed {
    Candidate candidate;
    int G = 0;
    int K = 0;
    vector<int> cuts;
    i128 lower_bound = kInf;
    string source;
};

struct BoundModel {
    vector<ResourceConstraint> constraints;
    i128 resident_per_layer = 0;
};

struct HeadTailData {
    vector<i128> head;
    vector<i128> tail;
};

struct FoldParent {
    int a = -1;
    int b = -1;
};

struct SeedSpec {
    int G = 0;
    int K = 0;
    vector<int> cuts;
};

SeedSpec schedule_seed_spec(const ScheduleResult& result) {
    return {result.G, result.K, result.cuts};
}

bool is_comm(int op) {
    for (int q : operation::kCommunicationOperations) {
        if (q == op) {
            return true;
        }
    }
    return false;
}

bool expired(Clock::time_point deadline) {
    return Clock::now() >= deadline;
}

vector<int> make_group_map(const vector<int>& cuts, int G, int L) {
    const int K = static_cast<int>(cuts.size()) - 1;
    vector<int> group(L, -1);
    for (int block = 0; block < K; ++block) {
        const int g = (K == G || block < G) ? block : 2 * G - 1 - block;
        for (int layer = cuts[block]; layer < cuts[block + 1]; ++layer) {
            group[layer] = g;
        }
    }
    return group;
}

vector<int> count_layers(const vector<int>& group, int G) {
    vector<int> counts(G);
    for (int g : group) {
        if (g >= 0 && g < G) {
            ++counts[g];
        }
    }
    return counts;
}

vector<i128> sample_thresholds(vector<i128> values) {
    sort(values.begin(), values.end());
    values.erase(unique(values.begin(), values.end()), values.end());
    vector<i128> chosen{0};
    if (values.empty()) {
        return chosen;
    }
    if (static_cast<int>(values.size()) <= kConstraintThresholds) {
        chosen.insert(chosen.end(), values.begin(), values.end());
    } else {
        for (int q = 0; q < kConstraintThresholds; ++q) {
            size_t at = static_cast<size_t>(q) * (values.size() - 1) /
                        static_cast<size_t>(kConstraintThresholds - 1);
            chosen.push_back(values[at]);
        }
    }
    sort(chosen.begin(), chosen.end());
    chosen.erase(unique(chosen.begin(), chosen.end()), chosen.end());
    return chosen;
}

bool build_head_tail(const InputData& x, const vector<array<i128, operation::kCount>>& dur,
                     HeadTailData& result, Clock::time_point deadline) {
    const int L = x.L;
    const int nodes = L * operation::kCount;
    vector<vector<int>> pred(nodes), succ(nodes);
    auto id = [L](int, int layer, int op) { return layer * operation::kCount + op; };
    for (int layer = 0; layer < L; ++layer) {
        operation_graph::append_layer_edges(0, layer, L, id, [&](int a, int b) {
            succ[a].push_back(b);
            pred[b].push_back(a);
        });
        if ((layer & 7) == 0 && expired(deadline)) {
            return false;
        }
    }

    vector<int> indegree(nodes);
    for (int node = 0; node < nodes; ++node) {
        indegree[node] = static_cast<int>(pred[node].size());
    }
    vector<int> ready;
    for (int node = 0; node < nodes; ++node) {
        if (indegree[node] == 0) {
            ready.push_back(node);
        }
    }
    vector<int> order;
    order.reserve(nodes);
    for (size_t at = 0; at < ready.size(); ++at) {
        const int node = ready[at];
        order.push_back(node);
        for (int next : succ[node]) {
            if (--indegree[next] == 0) {
                ready.push_back(next);
            }
        }
    }
    if (static_cast<int>(order.size()) != nodes) {
        return false;
    }

    const int words = (nodes + 63) / 64;
    vector<vector<uint64_t>> ancestors(nodes, vector<uint64_t>(words));
    vector<vector<uint64_t>> descendants(nodes, vector<uint64_t>(words));
    for (int node : order) {
        for (int p : pred[node]) {
            ancestors[node][p / 64] |= uint64_t{1} << (p % 64);
            for (int w = 0; w < words; ++w) {
                ancestors[node][w] |= ancestors[p][w];
            }
        }
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        const int node = *it;
        for (int s : succ[node]) {
            descendants[node][s / 64] |= uint64_t{1} << (s % 64);
            for (int w = 0; w < words; ++w) {
                descendants[node][w] |= descendants[s][w];
            }
        }
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }

    result.head.assign(nodes, 0);
    result.tail.assign(nodes, 0);
    auto resource_work = [&](const vector<uint64_t>& related, int layer, int engine,
                             const vector<i128>& releases) {
        vector<i128> values;
        for (int word = 0; word < words; ++word) {
            uint64_t bits = related[word];
            while (bits != 0) {
                const int bit = __builtin_ctzll(bits);
                const int n = word * 64 + bit;
                bits &= bits - 1;
                if (n >= nodes || n / operation::kCount != layer) {
                    continue;
                }
                const int op = n % operation::kCount;
                if (dur[layer][op] > 0 && static_cast<int>(is_comm(op)) == engine) {
                    values.push_back(releases[n]);
                }
            }
        }
        if (values.empty()) {
            return i128{0};
        }
        sort(values.begin(), values.end());
        values.erase(unique(values.begin(), values.end()), values.end());
        i128 bound = 0;
        for (i128 release : values) {
            i128 work = 0;
            for (int word = 0; word < words; ++word) {
                uint64_t bits = related[word];
                while (bits != 0) {
                    const int bit = __builtin_ctzll(bits);
                    const int n = word * 64 + bit;
                    bits &= bits - 1;
                    if (n >= nodes || n / operation::kCount != layer) {
                        continue;
                    }
                    const int op = n % operation::kCount;
                    if (dur[layer][op] > 0 && static_cast<int>(is_comm(op)) == engine &&
                        releases[n] >= release) {
                        work += dur[layer][op];
                    }
                }
            }
            bound = max(bound, release + work);
        }
        return bound;
    };

    for (int node : order) {
        i128 value = 0;
        for (int p : pred[node]) {
            value = max(value, result.head[p] + dur[p / operation::kCount][p % operation::kCount]);
        }
        const int layer = node / operation::kCount;
        const int op = node % operation::kCount;
        value = max(value, resource_work(ancestors[node], layer, is_comm(op), result.head));
        result.head[node] = value;
    }
    for (auto it = order.rbegin(); it != order.rend(); ++it) {
        const int node = *it;
        i128 value = 0;
        for (int s : succ[node]) {
            value = max(value, result.tail[s] + dur[s / operation::kCount][s % operation::kCount]);
        }
        const int layer = node / operation::kCount;
        const int op = node % operation::kCount;
        value = max(value, resource_work(descendants[node], layer, is_comm(op), result.tail));
        result.tail[node] = value;
        if ((node & 31) == 0 && expired(deadline)) {
            return false;
        }
    }
    return true;
}

bool build_bound_model(const InputData& x, const Candidate& c,
                       const vector<array<i128, operation::kCount>>& dur, BoundModel& model,
                       Clock::time_point deadline) {
    model.resident_per_layer = (x.E / c.P) * x.Z + x.Zs;
    if (model.resident_per_layer < 0) {
        return false;
    }
    HeadTailData ht;
    if (!build_head_tail(x, dur, ht, deadline)) {
        return false;
    }
    vector<i128> releases[2], tails[2];
    for (int layer = 0; layer < x.L; ++layer) {
        for (int op = 0; op < operation::kCount; ++op) {
            if (dur[layer][op] <= 0) {
                continue;
            }
            const int e = is_comm(op);
            releases[e].push_back(ht.head[layer * operation::kCount + op]);
            tails[e].push_back(ht.tail[layer * operation::kCount + op]);
        }
    }
    vector<i128> rs[2], qs[2];
    for (int e = 0; e < 2; ++e) {
        rs[e] = sample_thresholds(move(releases[e]));
        qs[e] = sample_thresholds(move(tails[e]));
    }
    for (int e = 0; e < 2; ++e) {
        for (i128 R : rs[e]) {
            for (i128 Q : qs[e]) {
                ResourceConstraint constraint;
                constraint.release = R;
                constraint.tail = Q;
                constraint.engine = e;
                constraint.prefix.assign(x.L + 1, 0);
                for (int layer = 0; layer < x.L; ++layer) {
                    i128 weight = 0;
                    for (int op = 0; op < operation::kCount; ++op) {
                        const int node = layer * operation::kCount + op;
                        if (static_cast<int>(is_comm(op)) == e && dur[layer][op] > 0 &&
                            ht.head[node] >= R && ht.tail[node] >= Q) {
                            weight += dur[layer][op];
                        }
                    }
                    constraint.prefix[layer + 1] = constraint.prefix[layer] + weight;
                }
                if (constraint.prefix.back() > 0) {
                    model.constraints.push_back(move(constraint));
                }
                if (expired(deadline)) {
                    return false;
                }
            }
        }
    }
    return !model.constraints.empty();
}

vector<vector<i128>> segment_costs(const InputData& x, const BoundModel& model,
                                   Clock::time_point deadline) {
    const int n = x.L + 1;
    vector<vector<i128>> costs(n, vector<i128>(n, kInf));
    for (int i = 0; i < x.L; ++i) {
        for (int j = i + 1; j <= x.L; ++j) {
            if ((i128)(j - i) * model.resident_per_layer > x.M) {
                continue;
            }
            i128 best = 0;
            for (const ResourceConstraint& c : model.constraints) {
                const i128 work = c.prefix[j] - c.prefix[i];
                if (work > 0) {
                    best = max(best, c.release + c.tail + (i128)x.mb * work);
                }
            }
            costs[i][j] = best;
        }
        if ((i & 3) == 0 && expired(deadline)) {
            return {};
        }
    }
    return costs;
}

vector<LayoutSeed> contiguous_dp(const InputData& x, const Candidate& c, const BoundModel& model,
                                 int max_groups, Clock::time_point deadline) {
    vector<LayoutSeed> out;
    const int n = x.L + 1;
    auto cost = segment_costs(x, model, deadline);
    if (cost.empty()) {
        return out;
    }
    vector<vector<i128>> dp(max_groups + 1, vector<i128>(n, kInf));
    vector<vector<int>> parent(max_groups + 1, vector<int>(n, -1));
    dp[0][0] = 0;
    for (int g = 1; g <= max_groups; ++g) {
        for (int j = g; j <= x.L; ++j) {
            for (int i = g - 1; i < j; ++i) {
                if (dp[g - 1][i] >= kInf || cost[i][j] >= kInf) {
                    continue;
                }
                const i128 value = max(dp[g - 1][i], cost[i][j]);
                if (value < dp[g][j]) {
                    dp[g][j] = value;
                    parent[g][j] = i;
                }
            }
            if ((j & 15) == 0 && expired(deadline)) {
                return out;
            }
        }
        if (dp[g][x.L] < kInf) {
            vector<int> cuts(g + 1);
            int at = x.L;
            cuts[g] = x.L;
            bool valid = true;
            for (int q = g; q > 0; --q) {
                const int prev = parent[q][at];
                if (prev < 0) {
                    valid = false;
                    break;
                }
                cuts[q - 1] = prev;
                at = prev;
            }
            if (valid) {
                LayoutSeed seed{c, g, g, cuts, dp[g][x.L], "threshold_dp_contiguous"};
                seed.candidate.V = g;
                seed.candidate.cuts = cuts;
                out.push_back(move(seed));
            }
        }
    }
    return out;
}

size_t choose4(int n) {
    if (n < 4) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) * (n - 2) * (n - 3) / 24;
}

size_t choose3(int n) {
    if (n < 3) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) * (n - 2) / 6;
}

size_t choose2(int n) {
    if (n < 2) {
        return 0;
    }
    return static_cast<size_t>(n) * (n - 1) / 2;
}

size_t colex_rank(int i, int a, int b, int j) {
    return choose4(j) + choose3(b) + choose2(a) + static_cast<size_t>(i);
}

vector<LayoutSeed> folded_dp(const InputData& x, const Candidate& c, const BoundModel& model,
                             int max_groups, const vector<vector<i128>>& segment_cost,
                             Clock::time_point deadline) {
    vector<LayoutSeed> out;
    const int n = x.L + 1;
    if (max_groups <= 0 || segment_cost.empty()) {
        return out;
    }
    const size_t cache_size = choose4(n);
    if (cache_size > kMaxFoldCacheEntries) {
        return out;
    }
    vector<i128> outside_cache(cache_size, kInf);
    vector<uint8_t> computed(cache_size, 0);
    auto outside_cost = [&](int i, int a, int b, int j) {
        const size_t index = colex_rank(i, a, b, j);
        if (!computed[index]) {
            const int layers = (a - i) + (j - b);
            if ((i128)layers * model.resident_per_layer > x.M) {
                outside_cache[index] = kInf;
            } else {
                i128 best = 0;
                for (const ResourceConstraint& q : model.constraints) {
                    const i128 work = q.prefix[a] - q.prefix[i] + q.prefix[j] - q.prefix[b];
                    if (work > 0) {
                        best = max(best, q.release + q.tail + (i128)x.mb * work);
                    }
                }
                outside_cache[index] = best;
            }
            computed[index] = 1;
        }
        return outside_cache[index];
    };

    vector<vector<i128>> previous(n, vector<i128>(n, kInf));
    for (int i = 0; i < x.L; ++i) {
        for (int j = i + 2; j <= x.L; ++j) {
            previous[i][j] = segment_cost[i][j];
        }
    }
    const size_t parent_size = static_cast<size_t>(max_groups + 1) * n * n;
    vector<FoldParent> parents(parent_size);
    auto pindex = [n](int g, int i, int j) { return (static_cast<size_t>(g) * n + i) * n + j; };
    size_t transitions = 0;
    for (int g = 1; g <= max_groups; ++g) {
        if (g >= 2) {
            vector<vector<i128>> current(n, vector<i128>(n, kInf));
            for (int i = 0; i + 2 * g <= x.L; ++i) {
                for (int j = i + 2 * g; j <= x.L; ++j) {
                    for (int a = i + 1; a + 2 * (g - 1) < j; ++a) {
                        const int b_min = a + 2 * (g - 1);
                        for (int b = b_min; b < j; ++b) {
                            if (((++transitions) & 255U) == 0U && expired(deadline)) {
                                return out;
                            }
                            const i128 inner = previous[a][b];
                            if (inner >= kInf) {
                                continue;
                            }
                            const i128 outer = outside_cost(i, a, b, j);
                            if (outer >= kInf) {
                                continue;
                            }
                            const i128 value = max(inner, outer);
                            if (value < current[i][j]) {
                                current[i][j] = value;
                                parents[pindex(g, i, j)] = {a, b};
                            }
                        }
                    }
                    if ((j & 3) == 0 && expired(deadline)) {
                        return out;
                    }
                }
            }
            previous.swap(current);
        }
        if (previous[0][x.L] < kInf) {
            vector<pair<int, int>> left(max_groups), right(max_groups);
            auto recover = [&](auto&& self, int q, int i, int j) -> bool {
                const int group = g - q;
                if (q == 1) {
                    const int mid = i + (j - i) / 2;
                    if (mid <= i || mid >= j) {
                        return false;
                    }
                    left[group] = {i, mid};
                    right[group] = {mid, j};
                    return true;
                }
                const FoldParent split = parents[pindex(q, i, j)];
                if (split.a < 0) {
                    return false;
                }
                left[group] = {i, split.a};
                right[group] = {split.b, j};
                return self(self, q - 1, split.a, split.b);
            };
            if (recover(recover, g, 0, x.L)) {
                vector<int> cuts;
                cuts.reserve(2 * g + 1);
                cuts.push_back(0);
                for (int q = 0; q < g; ++q) {
                    cuts.push_back(left[q].second);
                }
                for (int q = g - 1; q >= 0; --q) {
                    cuts.push_back(right[q].second);
                }
                if (static_cast<int>(cuts.size()) == 2 * g + 1 && cuts.back() == x.L) {
                    LayoutSeed seed{c, g, 2 * g, cuts, previous[0][x.L], "threshold_dp_folded"};
                    seed.candidate.V = 2 * g;
                    seed.candidate.cuts = cuts;
                    out.push_back(move(seed));
                }
            }
        }
        if (expired(deadline)) {
            return out;
        }
    }
    return out;
}

bool valid_cuts(const vector<int>& cuts, int L, int G, int K) {
    if (K != G && K != 2 * G) {
        return false;
    }
    if (static_cast<int>(cuts.size()) != K + 1 || cuts.front() != 0 || cuts.back() != L) {
        return false;
    }
    for (int j = 1; j <= K; ++j) {
        if (cuts[j] <= cuts[j - 1]) {
            return false;
        }
    }
    return true;
}

bool valid_candidate_map(const InputData& x, const Candidate& candidate) {
    if (candidate.P <= 0 || candidate.map.size() != static_cast<size_t>(x.L)) {
        return false;
    }
    for (const vector<int>& row : candidate.map) {
        if (row.size() != static_cast<size_t>(x.E)) {
            return false;
        }
        for (int rank : row) {
            if (rank < 0 || rank >= candidate.P) {
                return false;
            }
        }
    }
    return true;
}

i128 layout_bound(const InputData& x, const BoundModel& model, const vector<int>& cuts, int G,
                  Clock::time_point deadline = Clock::time_point::max()) {
    const int K = static_cast<int>(cuts.size()) - 1;
    vector<vector<pair<int, int>>> blocks(G);
    for (int j = 0; j < K; ++j) {
        const int g = (K == G || j < G) ? j : 2 * G - 1 - j;
        blocks[g].push_back({cuts[j], cuts[j + 1]});
    }
    i128 value = 0;
    for (const auto& group_blocks : blocks) {
        int layers = 0;
        for (auto [a, b] : group_blocks) {
            layers += b - a;
        }
        if (layers * model.resident_per_layer > x.M) {
            return kInf;
        }
        for (const ResourceConstraint& constraint : model.constraints) {
            i128 work = 0;
            for (auto [a, b] : group_blocks) {
                work += constraint.prefix[b] - constraint.prefix[a];
            }
            if (work > 0) {
                value = max(value, constraint.release + constraint.tail + (i128)x.mb * work);
            }
        }
        if (expired(deadline)) {
            return kInf;
        }
    }
    return value;
}

void add_layout(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                const Candidate& c, int G, const vector<int>& cuts, const string& source,
                Clock::time_point deadline = Clock::time_point::max()) {
    if (expired(deadline)) {
        return;
    }
    const int K = static_cast<int>(cuts.size()) - 1;
    if (G <= 0 || G > x.N * x.S / c.P || !valid_cuts(cuts, x.L, G, K)) {
        return;
    }
    for (const LayoutSeed& old : layouts) {
        if (old.candidate.P == c.P && old.G == G && old.K == K && old.cuts == cuts) {
            return;
        }
    }
    LayoutSeed seed{c, G, K, cuts, layout_bound(x, model, cuts, G, deadline), source};
    seed.candidate.V = K;
    seed.candidate.cuts = cuts;
    if (seed.lower_bound < kInf) {
        layouts.push_back(move(seed));
    }
}

void seed_neighborhood(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                       const Candidate& c, int G, int K, const vector<int>& cuts,
                       Clock::time_point deadline = Clock::time_point::max()) {
    add_layout(layouts, x, model, c, G, cuts, "placement_seed", deadline);
    if (K == 2 * G) {
        for (int j = 1; j < G; ++j) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                moved[K - j] += delta;
                add_layout(layouts, x, model, c, G, moved, "mirror_pair_shift", deadline);
            }
        }
        vector<int> selected;
        for (int j = 1; j < G; ++j) {
            if (j <= 3 || j >= G - 3 || j % max(1, G / 4) == 0) {
                selected.push_back(j);
            }
        }
        if (selected.size() > 8) {
            vector<int> sampled;
            for (int q = 0; q < 8; ++q) {
                sampled.push_back(selected[q * (selected.size() - 1) / 7]);
            }
            selected.swap(sampled);
        }
        for (size_t a = 0; a < selected.size(); ++a) {
            if (expired(deadline)) {
                return;
            }
            for (size_t b = a + 1; b < selected.size(); ++b) {
                for (int da : {-1, 1}) {
                    for (int db : {-1, 1}) {
                        vector<int> moved = cuts;
                        const int j = selected[a];
                        const int k = selected[b];
                        moved[j] += da;
                        moved[K - j] += da;
                        moved[k] += db;
                        moved[K - k] += db;
                        add_layout(layouts, x, model, c, G, moved, "mirror_two_pair_shift",
                                   deadline);
                    }
                }
            }
        }
        vector<int> single_positions;
        for (int j : {1, 2, G - 1, G, G + 1, K - 2, K - 1}) {
            if (j >= 1 && j < K &&
                find(single_positions.begin(), single_positions.end(), j) ==
                    single_positions.end()) {
                single_positions.push_back(j);
            }
        }
        for (int j : single_positions) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                add_layout(layouts, x, model, c, G, moved, "folded_single_cut_shift", deadline);
            }
        }
    } else {
        for (int j = 1; j < K; ++j) {
            if (expired(deadline)) {
                return;
            }
            for (int delta : {-1, 1}) {
                vector<int> moved = cuts;
                moved[j] += delta;
                add_layout(layouts, x, model, c, G, moved, "single_cut_shift", deadline);
            }
        }
    }
}

void interpolate_layouts(vector<LayoutSeed>& layouts, const InputData& x, const BoundModel& model,
                         const Candidate& c, const LayoutSeed& old, const LayoutSeed& fresh,
                         Clock::time_point deadline = Clock::time_point::max()) {
    const LayoutSeed old_copy = old;
    const LayoutSeed fresh_copy = fresh;
    if (old_copy.G != fresh_copy.G || old_copy.K != fresh_copy.K ||
        old_copy.candidate.P != fresh_copy.candidate.P) {
        return;
    }
    for (int numerator : {1, 2, 3, 4, 5, 7, 8, 9, 11, 12, 13, 15}) {
        if (expired(deadline)) {
            return;
        }
        constexpr int denominator = 16;
        vector<int> cuts(old_copy.K + 1);
        cuts[0] = 0;
        cuts[old_copy.K] = x.L;
        for (int j = 1; j < old_copy.K; ++j) {
            const i128 value = (i128)(denominator - numerator) * old_copy.cuts[j] +
                               (i128)numerator * fresh_copy.cuts[j];
            cuts[j] = static_cast<int>((value + denominator / 2) / denominator);
        }
        for (int j = 1; j < old_copy.K; ++j) {
            cuts[j] = max(cuts[j], cuts[j - 1] + 1);
        }
        for (int j = old_copy.K - 1; j > 0; --j) {
            cuts[j] = min(cuts[j], cuts[j + 1] - 1);
        }
        add_layout(layouts, x, model, c, old_copy.G, cuts, "seed_dp_interpolation", deadline);
    }
}

bool build_memory_caps(const InputData& x, const Candidate& c, const vector<int>& group,
                       const vector<int>& group_layers,
                       const vector<array<i128, operation::kCount>>& dur, vector<int>& caps,
                       vector<int>& buffers) {
    const int G = static_cast<int>(group_layers.size());
    const i128 resident = (x.E / c.P) * x.Z + x.Zs;
    caps.assign(G, 0);
    buffers.assign(G, 0);
    for (int g = 0; g < G; ++g) {
        bool has_comm = false;
        for (int layer = 0; layer < x.L; ++layer) {
            if (group[layer] != g) {
                continue;
            }
            for (int op : operation::kCommunicationOperations) {
                has_comm = has_comm || dur[layer][op] > 0;
            }
        }
        const int b = has_comm ? 1 : 0;
        const i128 available = x.M - (i128)group_layers[g] * resident - (has_comm ? x.U : 0);
        if (available < 0) {
            return false;
        }
        buffers[g] = b;
        if (x.Ua > 0) {
            caps[g] = static_cast<int>(min<i128>(available / x.Ua, (i128)x.mb * group_layers[g]));
        } else {
            caps[g] = x.mb * group_layers[g];
        }
        if (caps[g] < group_layers[g]) {
            return false;
        }
    }
    return true;
}

bool same_layout(const ScheduleResult& a, const ScheduleResult& b) {
    return a.c.P == b.c.P && a.G == b.G && a.K == b.K && a.cuts == b.cuts;
}

void normalize_schedule_order(vector<event_sched::Op>& ops) {
    stable_sort(ops.begin(), ops.end(), [](const event_sched::Op& a, const event_sched::Op& b) {
        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
    });
}

void retain_result(vector<ScheduleResult>& results, ScheduleResult result, ScheduleResult& best) {
    if (result.time < best.time) {
        best = result;
    }
    for (ScheduleResult& old : results) {
        if (same_layout(old, result)) {
            if (result.time < old.time) {
                old = move(result);
            }
            return;
        }
    }
    results.push_back(move(result));
}

bool evaluate_layout(const InputData& x, const LayoutSeed& seed,
                     const vector<array<i128, operation::kCount>>& dur, Clock::time_point deadline,
                     ScheduleResult& result) {
    if (expired(deadline)) {
        return false;
    }
    const vector<int> group = make_group_map(seed.cuts, seed.G, x.L);
    const vector<int> group_layers = count_layers(group, seed.G);
    if (any_of(group_layers.begin(), group_layers.end(), [](int n) { return n <= 0; })) {
        return false;
    }
    vector<int> caps, buffers;
    const bool event_memory_ok =
        build_memory_caps(x, seed.candidate, group, group_layers, dur, caps, buffers);

    result.c = seed.candidate;
    result.c.cuts = seed.cuts;
    result.c.V = seed.K;
    result.G = seed.G;
    result.K = seed.K;
    result.cuts = seed.cuts;
    result.group = group;
    result.time = kInf;
    scheduling::ProblemView problem{x.mb, x.L, seed.G, group, dur, group_layers};

    auto accept = [&](vector<event_sched::Op>& ops, i128 time) {
        if (time >= result.time ||
            ops.size() != static_cast<size_t>(x.mb * x.L * operation::kCount)) {
            return;
        }
        ScheduleResult trial = result;
        trial.time = time;
        trial.ops = ops;
        normalize_schedule_order(trial.ops);
        if (is_feasible_schedule(x, trial)) {
            result = move(trial);
        }
    };

    if (event_memory_ok) {
        for (int mode : {0, 1}) {
            if (expired(deadline)) {
                break;
            }
            vector<event_sched::Op> ops;
            i128 time = kInf;
            scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
            scheduling::EventConfig config;
            config.activation_capacity = &caps;
            config.communication_buffers = &buffers;
            config.window = 0;
            config.mode = mode;
            scheduling::ScheduleOutput output{ops, time};
            if (scheduler.run(config, output)) {
                accept(ops, time);
            }
        }
    }

    vector<scheduling::ListConfig> configs(1);
    configs[0].window = x.mb;
    configs[0].variant = 0;
    configs[0].fill_gaps = true;
    scheduling::ListConfig wave_a;
    wave_a.window = x.mb;
    wave_a.fill_gaps = true;
    wave_a.wave_rank = true;
    wave_a.rank_mode = 2;
    wave_a.rank_a = 1;
    wave_a.rank_b = 1;
    wave_a.pitch_numerator = 2;
    wave_a.pitch_denominator = 1;
    wave_a.duration_head = 1;
    wave_a.weight_gradient_order = 0;
    configs.push_back(wave_a);
    scheduling::ListConfig wave_b = wave_a;
    wave_b.pitch_numerator = 4;
    wave_b.pitch_denominator = 3;
    wave_b.duration_head = 2;
    wave_b.weight_gradient_order = 1;
    configs.push_back(wave_b);
    for (const scheduling::ListConfig& config : configs) {
        if (expired(deadline)) {
            break;
        }
        vector<event_sched::Op> ops;
        i128 time = kInf;
        scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
        scheduling::ScheduleOutput output{ops, time};
        if (scheduler.run(config, output)) {
            accept(ops, time);
        }
    }
    return result.time < kInf;
}

}  // namespace

vector<ScheduleResult> search_layout_bounds(const InputData& x,
                                            const vector<PartitionCandidate>& placements,
                                            ScheduleResult& best,
                                            chrono::steady_clock::time_point deadline) {
    vector<ScheduleResult> results;
    if (best.time < kInf) {
        ScheduleResult normalized_best = best;
        normalize_schedule_order(normalized_best.ops);
        if (is_feasible_schedule(x, normalized_best)) {
            best = normalized_best;
            results.push_back(move(normalized_best));
        }
    }
    if (expired(deadline)) {
        return results;
    }

    struct PlacementWork {
        int P = 0;
        Candidate representative;
        vector<SeedSpec> seeds;
    };
    vector<PlacementWork> work;
    auto add_candidate = [&](const Candidate& candidate) {
        if (!valid_candidate_map(x, candidate) || candidate.P > min(x.E, x.N * x.S) ||
            x.E % candidate.P != 0 || (x.S % candidate.P != 0 && candidate.P % x.S != 0) ||
            candidate.V > x.N * x.S / candidate.P ||
            candidate.V != static_cast<int>(candidate.cuts.size()) - 1 ||
            !valid_cuts(candidate.cuts, x.L, candidate.V, candidate.V)) {
            return;
        }
        auto it = find_if(work.begin(), work.end(),
                          [&](const PlacementWork& item) { return item.P == candidate.P; });
        if (it == work.end()) {
            PlacementWork item;
            item.P = candidate.P;
            item.representative = candidate;
            item.seeds.push_back({candidate.V, candidate.V, candidate.cuts});
            work.push_back(move(item));
        } else {
            for (const SeedSpec& old : it->seeds) {
                if (old.G == candidate.V && old.K == candidate.V && old.cuts == candidate.cuts) {
                    return;
                }
            }
            it->seeds.push_back({candidate.V, candidate.V, candidate.cuts});
        }
    };
    for (const PartitionCandidate& placement : placements) {
        add_candidate(placement.best_v);
        add_candidate(placement.max_v);
    }
    if (valid_candidate_map(x, best.c)) {
        auto it = find_if(work.begin(), work.end(),
                          [&](const PlacementWork& item) { return item.P == best.c.P; });
        if (it == work.end()) {
            PlacementWork item;
            item.P = best.c.P;
            item.representative = best.c;
            work.push_back(move(item));
            it = prev(work.end());
        } else if (best.c.map.size() == static_cast<size_t>(x.L)) {
            // All layouts for one P use one MAP, so durations and bounds agree.
            it->representative = best.c;
        }
        if (best.G > 0 && (best.K == best.G || best.K == 2 * best.G) &&
            best.cuts.size() == static_cast<size_t>(best.K + 1)) {
            bool duplicate = false;
            for (const SeedSpec& seed : it->seeds) {
                duplicate =
                    duplicate || (seed.G == best.G && seed.K == best.K && seed.cuts == best.cuts);
            }
            if (!duplicate) {
                it->seeds.push_back(schedule_seed_spec(best));
            }
        }
    }
    if (work.empty()) {
        return results;
    }

    // Preserve baseline/neighbor layouts for every P before spending time on DP.
    vector<LayoutSeed> layouts;
    vector<BoundModel> models(work.size());
    vector<vector<array<i128, operation::kCount>>> durations(work.size());
    const auto stage_start = Clock::now();
    const auto total_budget = deadline - stage_start;
    const auto prep_deadline = stage_start + total_budget / 3;
    const auto dp_stage_deadline = stage_start + (total_budget * 2) / 3;
    size_t remaining_prep = work.size();
    for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
        --remaining_prep;
        const auto now = Clock::now();
        const auto remaining = max(Clock::duration::zero(), prep_deadline - now);
        const auto slice = remaining_prep == 0
                               ? remaining
                               : remaining / static_cast<Clock::duration::rep>(remaining_prep + 1);
        const auto p_prep_deadline = min(prep_deadline, now + slice);
        durations[p] = compute_durations(x, work[p].representative);
        if (!build_bound_model(x, work[p].representative, durations[p], models[p],
                               p_prep_deadline)) {
            continue;
        }
        for (const SeedSpec& seed : work[p].seeds) {
            if (seed.G > 0 && seed.G <= x.N * x.S / work[p].P &&
                valid_cuts(seed.cuts, x.L, seed.G, seed.K)) {
                seed_neighborhood(layouts, x, models[p], work[p].representative, seed.G, seed.K,
                                  seed.cuts, p_prep_deadline);
            }
        }
    }

    // Fairly divide the optimization window across distinct P values. The
    // contiguous DP is cheap; folded DP may stop between complete group counts.
    size_t remaining_placements = work.size();
    for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
        --remaining_placements;
        if (models[p].constraints.empty()) {
            continue;
        }
        const auto now = Clock::now();
        const auto available = max(Clock::duration::zero(), dp_stage_deadline - now);
        const auto slice =
            remaining_placements == 0
                ? available
                : available / static_cast<Clock::duration::rep>(remaining_placements + 1);
        const auto p_deadline = min(dp_stage_deadline, now + slice);
        const int max_contiguous = min(x.L, x.N * x.S / work[p].P);
        vector<LayoutSeed> p_layouts =
            contiguous_dp(x, work[p].representative, models[p], max_contiguous, p_deadline);
        layouts.insert(layouts.end(), make_move_iterator(p_layouts.begin()),
                       make_move_iterator(p_layouts.end()));
        if (expired(p_deadline)) {
            continue;
        }
        const int max_folded = min(x.L / 2, x.N * x.S / work[p].P);
        if (max_folded <= 0) {
            continue;
        }
        const auto segment = segment_costs(x, models[p], p_deadline);
        if (segment.empty()) {
            continue;
        }
        vector<LayoutSeed> folded =
            folded_dp(x, work[p].representative, models[p], max_folded, segment, p_deadline);
        layouts.insert(layouts.end(), make_move_iterator(folded.begin()),
                       make_move_iterator(folded.end()));
    }

    // Add cut interpolations only where the exact P/G/K forms match.
    const size_t original_layout_count = layouts.size();
    for (size_t i = 0; i < original_layout_count && !expired(deadline); ++i) {
        for (size_t j = 0; j < original_layout_count && !expired(deadline); ++j) {
            if (layouts[i].source == "placement_seed" &&
                layouts[j].source.rfind("threshold_dp_", 0) == 0 &&
                layouts[i].candidate.P == layouts[j].candidate.P && layouts[i].G == layouts[j].G &&
                layouts[i].K == layouts[j].K) {
                const auto p_it = find_if(work.begin(), work.end(), [&](const PlacementWork& item) {
                    return item.P == layouts[i].candidate.P;
                });
                if (p_it != work.end()) {
                    const size_t p = static_cast<size_t>(p_it - work.begin());
                    const LayoutSeed old_layout = layouts[i];
                    const LayoutSeed dp_layout = layouts[j];
                    interpolate_layouts(layouts, x, models[p], p_it->representative, old_layout,
                                        dp_layout, dp_stage_deadline);
                }
            }
        }
    }

    // Retain a small lower-bound-ranked set per P so one placement cannot use
    // the whole schedule-evaluation window.
    vector<LayoutSeed> selected;
    for (const PlacementWork& item : work) {
        vector<LayoutSeed> local;
        for (const LayoutSeed& layout : layouts) {
            if (layout.candidate.P == item.P) {
                local.push_back(layout);
            }
        }
        stable_sort(local.begin(), local.end(), [](const LayoutSeed& a, const LayoutSeed& b) {
            return a.lower_bound < b.lower_bound;
        });
        if (local.size() > kMaxLayoutsPerPlacement) {
            local.resize(kMaxLayoutsPerPlacement);
        }
        selected.insert(selected.end(), make_move_iterator(local.begin()),
                        make_move_iterator(local.end()));
    }

    // Round-robin through P values and evaluate complete static schedules.
    vector<vector<LayoutSeed>> by_placement(work.size());
    for (LayoutSeed& layout : selected) {
        for (size_t p = 0; p < work.size(); ++p) {
            if (layout.candidate.P == work[p].P) {
                by_placement[p].push_back(move(layout));
                break;
            }
        }
    }
    vector<size_t> at(work.size(), 0);
    bool progress = true;
    while (progress && !expired(deadline)) {
        progress = false;
        for (size_t p = 0; p < work.size() && !expired(deadline); ++p) {
            if (at[p] >= by_placement[p].size()) {
                continue;
            }
            progress = true;
            const LayoutSeed& layout = by_placement[p][at[p]++];
            ScheduleResult candidate;
            if (evaluate_layout(x, layout, durations[p], deadline, candidate)) {
                retain_result(results, move(candidate), best);
            }
        }
    }

    stable_sort(results.begin(), results.end(),
                [](const ScheduleResult& a, const ScheduleResult& b) { return a.time < b.time; });
    if (results.size() > kSeedLimit) {
        results.resize(kSeedLimit);
    }
    return results;
}

}  // namespace solver
// END MODULE: src/search/layout_bound_search.cpp
// END TRANSLATION UNIT: src/search/layout_bound_search.cpp
// BEGIN TRANSLATION UNIT: src/search/priority_search.cpp
// BEGIN MODULE: src/search/priority_search.cpp


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
// END MODULE: src/search/priority_search.cpp
// END TRANSLATION UNIT: src/search/priority_search.cpp
// BEGIN TRANSLATION UNIT: src/search/window_search.cpp
// BEGIN MODULE: src/search/window_search.cpp
// BEGIN MODULE: src/search/window_search.hpp
namespace solver {
ScheduleResult scan_release1(const InputData& x, const ScheduleResult& anchor,
                             std::chrono::steady_clock::time_point deadline, bool& cutoff);
}
// END MODULE: src/search/window_search.hpp
// Release-one window sweep for the initial schedule.
namespace solver {
using namespace std;
ScheduleResult scan_release1(const InputData& x, const ScheduleResult& anchor,
                             chrono::steady_clock::time_point deadline, bool& cutoff) {
    ScheduleResult trial = anchor;
    auto dur = compute_durations(x, anchor.c);
    vector<int> ng(anchor.G);
    for (int g : anchor.group) {
        ++ng[g];
    }
    vector<int> wins;
    if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
        for (int w = 1; w <= x.mb; ++w) {
            wins.push_back(w);
        }
    } else {
        wins = {1,
                2,
                30,  // sampled window value retained for large batches

                31,
                32,
                search_limits::kWindowExhaustiveMicrobatchLimit,
                anchor.G,
                max(1, anchor.G - 1),
                anchor.G + 1,
                2 * anchor.G,
                max(1, 2 * anchor.G - 1),
                2 * anchor.G + 1,
                x.mb};
        for (int& w : wins) {
            w = min(w, x.mb);
        }
        sort(wins.begin(), wins.end());
        wins.erase(unique(wins.begin(), wins.end()), wins.end());
    }
    for (int one = 0; one <= 1 && !cutoff; ++one) {
        vector<int> caps(anchor.G), buf(anchor.G);
        bool ok = true;
        for (int g = 0; g < anchor.G; ++g) {
            bool zero = true;
            for (int l = 0; l < x.L; ++l) {
                if (anchor.group[l] == g &&
                    (dur[l][operation::index(operation::kDispatchForward)] ||
                     dur[l][operation::index(operation::kCombineForward)] ||
                     dur[l][operation::index(operation::kCombineBackward)] ||
                     dur[l][operation::index(operation::kDispatchBackward)])) {
                    zero = false;
                }
            }
            int b = zero ? 0 : 1;
            if (!zero && !one) {
                i128 two = x.M - (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - 2 * x.U;
                if (two >= 0 && two / x.Ua >= ng[g]) {
                    b = 2;
                }
            }
            i128 avail =
                x.M - (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
            if (avail < 0) {
                ok = false;
                break;
            }
            caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
            buf[g] = b;
            if (caps[g] < ng[g]) {
                ok = false;
                break;
            }
        }
        if (!ok) {
            continue;
        }
        for (int w : wins) {
            if (chrono::steady_clock::now() >= deadline) {
                cutoff = true;
                break;
            }
            vector<event_sched::Op> ops;
            i128 tm;
            scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
            scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
            scheduling::EventConfig config;
            config.activation_capacity = &caps;
            config.communication_buffers = &buf;
            config.window = w;
            config.window_release = 1;
            scheduling::ScheduleOutput output{ops, tm};
            if (scheduler.run(config, output) && tm < trial.time) {
                trial.time = tm;
                trial.ops.swap(ops);
            }
        }
    }
    return trial;
}

}  // namespace solver
// END MODULE: src/search/window_search.cpp
// END TRANSLATION UNIT: src/search/window_search.cpp
// BEGIN TRANSLATION UNIT: src/search/initial_search.cpp
// BEGIN MODULE: src/search/initial_search.cpp
// Select initial candidates and preserve the baseline incumbents.
namespace solver {
using namespace std;


InitialResults refine_initial_candidates(const InputData& x, vector<PartitionCandidate>& pcs,
                                         bool serial) {
    vector<ScheduleResult> probes;
    probes.reserve(pcs.size());
    for (auto& pc : pcs) {
        ScheduleResult r = evaluate_layouts(x, pc.max_v, false, false);
        pc.probe_time = r.time;
        probes.push_back(move(r));
    }
    int winner = 0;
    for (int i = 1; i < (int)probes.size(); i++) {
        if (probes[i].time < probes[winner].time) {
            winner = i;
        }
    }
    ScheduleResult best = move(probes[winner]);
    ScheduleResult probe_base = best;
    if (!serial) {
        vector<int> ord(pcs.size());
        iota(ord.begin(), ord.end(), 0);
        sort(ord.begin(), ord.end(),
             [&](int a, int b) { return pcs[a].probe_time < pcs[b].probe_time; });
        if (winner != ord[0]) {
            swap(ord[0], ord[find(ord.begin(), ord.end(), winner) - ord.begin()]);
        }
        for (int j = 0; j < min(2, (int)ord.size()); j++) {
            int id = ord[j];
            const Candidate& c = pcs[id].best_v.P ? pcs[id].best_v : pcs[id].max_v;
            ScheduleResult r = evaluate_layouts(x, c, true, j == 0);
            // Candidate replacement is strict on Time; equal values retain traversal order.
            if (r.time < best.time) {
                best = move(r);
            }
        }
    }
    // Freeze the complete v5 result, including its original P/V and rich schedule
    // competition. Every borrow experiment branches from this exact incumbent.
    ScheduleResult v5_base = best;
    return {move(best), move(probe_base), move(v5_base)};
}

}  // namespace solver
// END MODULE: src/search/initial_search.cpp
// END TRANSLATION UNIT: src/search/initial_search.cpp
// BEGIN TRANSLATION UNIT: src/search/window_borrow.cpp
// BEGIN MODULE: src/search/window_borrow.cpp
// Window-limit borrowing from frozen initial incumbents.
namespace solver {
using namespace std;
ScheduleResult run_window_borrow(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& probe_base, const ScheduleResult& v5_base,
                                 bool serial, const string& borrow) {
    if (!serial && (borrow == "windows" || borrow == "ac" || borrow == "all")) {
        auto scan_windows = [&](const ScheduleResult& anchor) {
            ScheduleResult trial = anchor;
            auto dur = compute_durations(x, anchor.c);
            vector<int> ng(anchor.G);
            for (int g : anchor.group) {
                ng[g]++;
            }
            vector<int> wins;
            if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
                for (int w = 1; w <= x.mb; w++) {
                    wins.push_back(w);
                }
            } else {
                wins = {1,
                        2,
                        30,  // sampled window value retained for large batches

                        31,
                        32,
                        search_limits::kWindowExhaustiveMicrobatchLimit,
                        0,
                        anchor.G,
                        2 * anchor.G,
                        max(1, anchor.G - 1),
                        anchor.G + 1,
                        max(1, 2 * anchor.G - 1),
                        2 * anchor.G + 1};
            }
            sort(wins.begin(), wins.end());
            wins.erase(unique(wins.begin(), wins.end()), wins.end());
            for (int one = 0; one <= 1; one++) {
                vector<int> caps(anchor.G), buf(anchor.G);
                bool ok = true;
                for (int g = 0; g < anchor.G; g++) {
                    bool zero = true;
                    for (int l = 0; l < x.L; l++) {
                        if (anchor.group[l] == g &&
                            (dur[l][operation::index(operation::kDispatchForward)] ||
                             dur[l][operation::index(operation::kCombineForward)] ||
                             dur[l][operation::index(operation::kCombineBackward)] ||
                             dur[l][operation::index(operation::kDispatchBackward)])) {
                            zero = false;
                        }
                    }
                    int b = zero ? 0 : 1;
                    if (!zero && !one) {
                        i128 two = x.M - ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - 2 * x.U;
                        if (two >= 0 && two / x.Ua >= ng[g]) {
                            b = 2;
                        }
                    }
                    i128 avail =
                        x.M - ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
                    if (avail < 0) {
                        ok = false;
                        break;
                    }
                    caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                    buf[g] = b;
                    if (caps[g] < ng[g]) {
                        ok = false;
                        break;
                    }
                }
                if (ok) {
                    for (int w : wins) {
                        vector<event_sched::Op> ops;
                        i128 tm;
                        scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
                        scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                        scheduling::EventConfig config;
                        config.activation_capacity = &caps;
                        config.communication_buffers = &buf;
                        config.window = w;
                        scheduling::ScheduleOutput output{ops, tm};
                        if (scheduler.run(config, output) && tm < trial.time) {
                            trial.time = tm;
                            trial.ops.swap(ops);
                        }
                    }
                }
            }
            return trial;
        };
        ScheduleResult a = scan_windows(probe_base), b = scan_windows(v5_base);
        ScheduleResult trial = (a.time <= b.time ? move(a) : move(b));
        if (trial.time < best.time) {
            best = move(trial);
        }
    }
    return best;
}

}  // namespace solver
// END MODULE: src/search/window_borrow.cpp
// END TRANSLATION UNIT: src/search/window_borrow.cpp
// BEGIN TRANSLATION UNIT: src/search/boost_search.cpp
// BEGIN MODULE: src/search/boost_search.cpp
// Forward-fill priority search.
namespace solver {
using namespace std;
ScheduleResult run_boost_borrow(const InputData& x, ScheduleResult best,
                                const ScheduleResult& v5_base, bool serial, const string& borrow) {
    if (!serial && (borrow == "boost" || borrow == "boost_grid" || borrow == "all")) {
        ScheduleResult trial = v5_base;
        auto dur = compute_durations(x, v5_base.c);
        vector<int> ng(v5_base.G);
        for (int g : v5_base.group) {
            ng[g]++;
        }
        i128 boost_best_time = search_limits::kInfiniteTime;
        int best_fg = 0, best_fm = 0, best_ratio = 0, best_buffer = 0;
        bool best_flat = false;
        for (int one = 0; one <= 1; one++) {
            vector<int> caps(v5_base.G), buf(v5_base.G);
            bool ok = true;
            for (int g = 0; g < v5_base.G; g++) {
                bool zero = true;
                for (int l = 0; l < x.L; l++) {
                    if (v5_base.group[l] == g &&
                        (dur[l][operation::index(operation::kDispatchForward)] ||
                         dur[l][operation::index(operation::kCombineForward)] ||
                         dur[l][operation::index(operation::kCombineBackward)] ||
                         dur[l][operation::index(operation::kDispatchBackward)])) {
                        zero = false;
                    }
                }
                int b = zero ? 0 : 1;
                if (!zero && !one) {
                    i128 two = x.M - ng[g] * ((x.E / v5_base.c.P) * x.Z + x.Zs) - 2 * x.U;
                    if (two >= 0 && two / x.Ua >= ng[g]) {
                        b = 2;
                    }
                }
                i128 avail =
                    x.M - ng[g] * ((x.E / v5_base.c.P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
                if (avail < 0) {
                    ok = false;
                    break;
                }
                caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                buf[g] = b;
                if (caps[g] < ng[g]) {
                    ok = false;
                    break;
                }
            }
            if (!ok) {
                continue;
            }
            vector<tuple<int, int, int, bool, bool>> cfg;
            if (borrow == "boost_grid") {
                set<int> fss = {1, 2, max(1, v5_base.G / 2), v5_base.G},
                         fms = {max(1, x.mb / 4), max(1, x.mb / 2), x.mb};
                vector<int> ratios = {0, 5, 10, 20, 50, 100};
                for (int fg : fss) {
                    for (int fm0 : fms) {
                        for (int ratio : ratios) {
                            cfg.emplace_back(fg, fm0, ratio, false, false);
                        }
                    }
                }
                cfg.emplace_back(min(2, v5_base.G), min(x.mb, max(1, x.mb / 2)), 20, true, false);
            } else {
                int fs = min(v5_base.G, max(1, v5_base.G / 2)), fm = min(x.mb, 16);
                cfg.emplace_back(v5_base.G, min(x.mb, max(2, v5_base.G)), 0, false, false);
                cfg.emplace_back(fs, fm, 10, false, false);
                cfg.emplace_back(fs, fm, 20, false, false);
                cfg.emplace_back(fs, fm, 50, false, false);
                cfg.emplace_back(min(2, v5_base.G), min(x.mb, 8), 20, true, false);
            }
            for (auto [fg, fm0, ratio, flat, unused] : cfg) {
                (void)unused;
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, v5_base.G, v5_base.group, dur, ng};
                scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                scheduling::EventConfig config;
                config.activation_capacity = &caps;
                config.communication_buffers = &buf;
                config.mode = 3;
                config.fill_groups = fg;
                config.fill_microbatches = fm0;
                config.reward_tenths = ratio;
                config.flat_reward = flat;
                scheduling::ScheduleOutput output{ops, tm};
                if (scheduler.run(config, output)) {
                    if (tm < boost_best_time) {
                        boost_best_time = tm;
                        best_fg = fg;
                        best_fm = fm0;
                        best_ratio = ratio;
                        best_flat = flat;
                        best_buffer = one;
                    }
                    if (tm < trial.time) {
                        trial.time = tm;
                        trial.ops.swap(ops);
                    }
                }
            }
        }
        if (borrow == "boost_grid" && boost_best_time < search_limits::kInfiniteTime) {
            cerr << "BORROW_B_GRID_BEST P=" << v5_base.c.P << " G=" << best_fg << " M=" << best_fm
                 << " ratio=" << best_ratio << " flat=" << best_flat << " buffer=" << best_buffer
                 << " Time=" << to_decimal(boost_best_time) << " base=" << to_decimal(v5_base.time)
                 << "\n";
        }
        if (trial.time < best.time) {
            best = move(trial);
        }
    }
    return best;
}

}  // namespace solver
// END MODULE: src/search/boost_search.cpp
// END TRANSLATION UNIT: src/search/boost_search.cpp
// BEGIN TRANSLATION UNIT: src/search/placement_search.cpp
// BEGIN MODULE: src/search/placement_search.cpp
// Alternative expert placement search and rescheduling.
namespace solver {
using namespace std;
ScheduleResult run_alt_placement(const InputData& x, ScheduleResult best,
                                 const ScheduleResult& v5_base, bool serial, const string& borrow) {
    if (!serial && (borrow == "placement" || borrow == "ac" || borrow == "all")) {
        Candidate alt = v5_base.c;
        const int P = alt.P, per = x.E / P;
        bool changed = false;
        int improved_layers = 0;
        map<vector<i128>, grouped_placement::Plan> cache;
        for (int l = 0; l < x.L; l++) {
            vector<i128> slots = x.load[l], key = slots;
            sort(key.begin(), key.end());
            vector<i128> base_load(P);
            for (int e = 0; e < x.E; e++) {
                base_load[alt.map[l][e]] += slots[e];
            }
            i128 cur = *max_element(base_load.begin(), base_load.end()),
                 total = accumulate(slots.begin(), slots.end(), (i128)0),
                 heavy = *max_element(slots.begin(), slots.end());
            i128 lower = max(ceil_div(total, P), heavy);
            if (cur <= lower) {
                continue;
            }
            grouped_placement::Plan plan;
            bool found = false;
            auto it = cache.find(key);
            if (it != cache.end()) {
                plan = it->second;
                found = true;
            } else {
                i128 lo = lower, hi = cur - 1;
                grouped_placement::Plan best_plan;
                for (int z = 0; z < search_limits::kPlacementPeakSearchSteps && lo <= hi; z++) {
                    i128 mid = lo + (hi - lo) / 2;
                    grouped_placement::Plan trial;
                    if (grouped_placement::find_at_peak(slots, P, per, mid, trial,
                                                        search_limits::kPlacementSearchBudget)) {
                        best_plan = move(trial);
                        hi = mid - 1;
                    } else {
                        lo = mid + 1;
                    }
                }
                if (best_plan.peak) {
                    plan = move(best_plan);
                    cache.emplace(key, plan);
                    found = true;
                }
            }
            if (!found) {
                continue;
            }
            vector<int> row;
            if (!grouped_placement::materialize(slots, plan, row)) {
                continue;
            }
            vector<i128> new_load(P);
            for (int e = 0; e < x.E; e++) {
                new_load[row[e]] += slots[e];
            }
            i128 nm = *max_element(new_load.begin(), new_load.end());
            if (nm < cur) {
                alt.map[l] = move(row);
                changed = true;
                ++improved_layers;
            }
        }
        if (changed) {
            ScheduleResult trial = v5_base;
            trial.c = alt;
            auto dur = compute_durations(x, alt);
            vector<int> ng(trial.G);
            for (int g : trial.group) {
                ng[g]++;
            }
            for (int one = 0; one <= 1; one++) {
                vector<int> caps(trial.G), buf(trial.G);
                bool ok = true;
                for (int g = 0; g < trial.G; g++) {
                    bool zero = true;
                    for (int l = 0; l < x.L; l++) {
                        if (trial.group[l] == g &&
                            (dur[l][operation::index(operation::kDispatchForward)] ||
                             dur[l][operation::index(operation::kCombineForward)] ||
                             dur[l][operation::index(operation::kCombineBackward)] ||
                             dur[l][operation::index(operation::kDispatchBackward)])) {
                            zero = false;
                        }
                    }
                    int b = zero ? 0 : 1;
                    if (!zero && !one) {
                        i128 two = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - 2 * x.U;
                        if (two >= 0 && two / x.Ua >= ng[g]) {
                            b = 2;
                        }
                    }
                    i128 avail = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
                    if (avail < 0) {
                        ok = false;
                        break;
                    }
                    caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                    buf[g] = b;
                    if (caps[g] < ng[g]) {
                        ok = false;
                        break;
                    }
                }
                if (!ok) {
                    continue;
                }
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, trial.G, trial.group, dur, ng};
                scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                scheduling::EventConfig config;
                config.activation_capacity = &caps;
                config.communication_buffers = &buf;
                scheduling::ScheduleOutput output{ops, tm};
                if (scheduler.run(config, output) && tm < trial.time) {
                    trial.time = tm;
                    trial.ops.swap(ops);
                }
            }
            if (borrow == "all" || borrow == "ac") {
                vector<int> wins;
                if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
                    for (int w = 1; w <= x.mb; w++) {
                        wins.push_back(w);
                    }
                } else {
                    wins = {1,          2, 30,      31,          32,
                            64,         0, trial.G, 2 * trial.G, max(1, trial.G - 1),
                            trial.G + 1};
                }
                sort(wins.begin(), wins.end());
                wins.erase(unique(wins.begin(), wins.end()), wins.end());
                for (int one = 0; one <= 1; one++) {
                    vector<int> caps(trial.G), buf(trial.G);
                    bool ok = true;
                    for (int g = 0; g < trial.G; g++) {
                        bool zero = true;
                        for (int l = 0; l < x.L; l++) {
                            if (trial.group[l] == g &&
                                (dur[l][operation::index(operation::kDispatchForward)] ||
                                 dur[l][operation::index(operation::kCombineForward)] ||
                                 dur[l][operation::index(operation::kCombineBackward)] ||
                                 dur[l][operation::index(operation::kDispatchBackward)])) {
                                zero = false;
                            }
                        }
                        int b = zero ? 0 : 1;
                        if (!zero && !one) {
                            i128 two = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - 2 * x.U;
                            if (two >= 0 && two / x.Ua >= ng[g]) {
                                b = 2;
                            }
                        }
                        i128 avail = x.M - ng[g] * ((x.E / P) * x.Z + x.Zs) - (zero ? 0 : b * x.U);
                        if (avail < 0) {
                            ok = false;
                            break;
                        }
                        caps[g] = (int)min<i128>(avail / x.Ua, (i128)x.mb * ng[g]);
                        buf[g] = b;
                        if (caps[g] < ng[g]) {
                            ok = false;
                            break;
                        }
                    }
                    if (!ok) {
                        continue;
                    }
                    for (int w : wins) {
                        vector<event_sched::Op> ops;
                        i128 tm;
                        scheduling::ProblemView problem{x.mb, x.L, trial.G, trial.group, dur, ng};
                        scheduling::Scheduler<scheduling::EventScheduleStrategy> scheduler(problem);
                        scheduling::EventConfig config;
                        config.activation_capacity = &caps;
                        config.communication_buffers = &buf;
                        config.window = w;
                        scheduling::ScheduleOutput output{ops, tm};
                        if (scheduler.run(config, output) && tm < trial.time) {
                            trial.time = tm;
                            trial.ops.swap(ops);
                        }
                    }
                }
            }
            if (trial.time < best.time) {
                best = move(trial);
                cerr << "BORROW_C P=" << P << " improved_MAP_layers=" << improved_layers
                     << " Time=" << to_decimal(best.time) << "\n";
            }
        }
    }
    return best;
}

}  // namespace solver
// END MODULE: src/search/placement_search.cpp
// END TRANSLATION UNIT: src/search/placement_search.cpp
// BEGIN TRANSLATION UNIT: src/search/list_search.cpp
// BEGIN MODULE: src/search/list_search.cpp
// List-scheduler strategy and its local parameter sweeps.
namespace solver {
using namespace std;
ScheduleResult run_v7_list_search(const InputData& x, ScheduleResult best, bool serial,
                                  bool do_list, bool list_deep, bool list_deep_topos,
                                  bool diff_enabled, chrono::steady_clock::time_point main_start,
                                  const string& borrow, chrono::steady_clock::time_point deadline) {
    if (!serial && do_list) {
        bool list_cutoff = false;
        const auto default_deadline =
            main_start + chrono::milliseconds(list_deep ? search_limits::kListDeepDeadlineMs
                                                        : search_limits::kListNormalDeadlineMs);
        const auto list_deadline = min(default_deadline, deadline);
        ScheduleResult anchor = best;
        auto dur = compute_durations(x, anchor.c);
        vector<int> ng(anchor.G);
        for (int g : anchor.group) {
            ng[g]++;
        }
        auto safe = [&](const vector<event_sched::Op>& ops, i128& tm) -> bool {
            int stride = x.L * operation::kCount, N = x.mb * stride;
            vector<i128> st(N, -1), en(N, -1);
            tm = 0;
            for (auto& o : ops) {
                int id = (o.mb * x.L + o.l) * operation::kCount + o.op;
                st[id] = o.start;
                en[id] = o.start + dur[o.l][o.op];
                tm = max(tm, en[id]);
            }
            for (int i = 0; i < N; i++) {
                if (st[i] < 0) {
                    return false;
                }
            }
            auto peak = [](vector<pair<i128, i128>>& a) {
                sort(a.begin(), a.end());
                multiset<i128> ends;
                int best = 0;
                for (size_t i = 0; i < a.size();) {
                    size_t j = i;
                    while (j < a.size() && a[j].first == a[i].first) {
                        j++;
                    }
                    while (!ends.empty() && *ends.begin() < a[i].first) {
                        ends.erase(ends.begin());
                    }
                    best = max(best, (int)ends.size() + (int)(j - i));
                    for (size_t k = i; k < j; k++) {
                        ends.insert(a[k].second);
                    }
                    i = j;
                }
                return best;
            };
            for (int g = 0; g < anchor.G; g++) {
                i128 mexp = (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs);
                vector<pair<i128, i128>> acts, comms;
                for (int l = 0; l < x.L; l++) {
                    if (anchor.group[l] == g) {
                        for (int m = 0; m < x.mb; m++) {
                            int b = (m * x.L + l) * operation::kCount;
                            acts.push_back({en[b + operation::index(operation::kCombineForward)],
                                            st[b + operation::index(operation::kSharedBackward)]});
                            for (int o : operation::kCommunicationOperations) {
                                if (dur[l][o] > 0) {
                                    comms.push_back({st[b + o], en[b + o]});
                                }
                            }
                        }
                    }
                }
                i128 used = mexp + x.U * peak(comms) + x.Ua * peak(acts);
                if (used > x.M) {
                    return false;
                }
            }
            return true;
        };
        i128 base_time = anchor.time, busy = 0;
        for (int g = 0; g < anchor.G; g++) {
            i128 csum = 0, msum = 0;
            for (int l = 0; l < x.L; l++) {
                if (anchor.group[l] == g) {
                    for (int o = 0; o < operation::kCount; o++) {
                        (list_sched::comm(o) ? msum : csum) += dur[l][o];
                    }
                }
            }
            busy = max(busy, max(csum, msum));
        }
        int best_w = 0, best_variant = -1, best_gap = 0;
        string best_mode = "incumbent";
        bool best_boost = false;
        long double best_boost_value = 0;
        int best_fs = 0, best_fm = 0, best_ratio = 0;
        bool best_ramp = false;
        i128 plain_time = search_limits::kInfiniteTime;
        int plain_w = x.mb;
        bool gap_improved = false, skip_sweep = false;
        auto run = [&](int W, int vi, bool early, int gap, int fs, int fm, int ratio10, bool ramp) {
            if (chrono::steady_clock::now() > list_deadline) {
                list_cutoff = true;
                return;
            }
            vector<event_sched::Op> ops;
            i128 tm;
            scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
            scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
            scheduling::ListConfig config;
            config.window = W;
            config.variant = vi;
            config.early = early;
            config.gap = gap;
            config.fill_groups = fs;
            config.fill_microbatches = fm;
            config.busy = busy;
            config.ratio_tenths = ratio10;
            config.ramp = ramp;
            scheduling::ScheduleOutput output{ops, tm};
            if (!scheduler.run(config, output)) {
                return;
            }
            if (tm >= best.time && (ratio10 > 0 || tm >= plain_time)) {
                return;
            }
            i128 checked;
            if (!safe(ops, checked)) {
                return;
            }
            if (ratio10 == 0 && checked < plain_time) {
                plain_time = checked;
                plain_w = W;
            }
            if (checked >= best.time) {
                return;
            }
            sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
            });
            best.time = checked;
            best.ops = move(ops);
            best_w = W;
            best_variant = vi;
            best_gap = gap;
            best_mode = early ? "early" : "prio";
            best_boost = ratio10 > 0;
            best_boost_value = (long double)busy * ratio10 / 10;
            best_fs = fs;
            best_fm = fm;
            best_ratio = ratio10;
            best_ramp = ramp;
        };
        i128 node_count = (i128)x.mb * x.L * operation::kCount;
        if (node_count >= 5000 && node_count <= 150000 &&
            chrono::steady_clock::now() <
                min(list_deadline,
                    main_start + chrono::milliseconds(search_limits::kQuickGapFillLatestStartMs))) {
            vector<event_sched::Op> ops;
            i128 tm;
            scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
            scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
            scheduling::ListConfig config;
            config.window = x.mb;
            config.wave_rank = true;
            config.fill_gaps = true;
            scheduling::ScheduleOutput output{ops, tm};
            if (scheduler.run(config, output) && tm < best.time) {
                i128 checked;
                if (safe(ops, checked) && checked < best.time) {
                    sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
                    });
                    best.time = checked;
                    best.ops = move(ops);
                    best_w = x.mb;
                    best_variant = 0;
                    best_gap = 0;
                    best_mode = "gap-fill";
                    best_boost = false;
                    gap_improved = true;
                }
            }
        }
        if (diff_enabled && borrow == "ac") {
            bool release_cutoff = false;
            ScheduleResult released = scan_release1(
                x, best,
                min(list_deadline,
                    main_start + chrono::milliseconds(search_limits::kListReleaseDeadlineMs)),
                release_cutoff);
            if (released.time < best.time) {
                best = move(released);
            }
            list_cutoff = list_cutoff || release_cutoff;
        }
        set<int> all_w;
        if (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit) {
            for (int w = 1; w <= x.mb; w++) {
                all_w.insert(w);
            }
        } else {
            for (int num : {1, 2}) {
                int w = x.mb * num / 2;
                if (w > 0) {
                    all_w.insert(w);
                }
            }
            for (auto [num, den] : vector<pair<int, int>>{{2, 3},
                                                          {1, 1},
                                                          {1, 2},
                                                          {1, 3},
                                                          {1, 4},
                                                          {1, 5},
                                                          {1, 6},
                                                          {1, 8},
                                                          {1, 12},
                                                          {1, 16},
                                                          {1, 24},
                                                          {1, 32}}) {
                int w = x.mb * num / den;
                if (w > 0) {
                    all_w.insert(w);
                }
            }
            for (int w : {32, 24, 16, 12, 8, 6, 4, 3, 2, 1}) {
                if (w <= x.mb) {
                    all_w.insert(w);
                }
            }
        }
        i128 per_layer = (x.E / anchor.c.P) * x.Z + x.Zs;
        if (x.Ua > 0) {
            for (int g = 0; g < anchor.G; g++) {
                i128 mexp = (i128)ng[g] * per_layer, allowed = (x.M - mexp - x.U) / x.Ua;
                if (allowed > 0 && ng[g] > 0) {
                    all_w.insert(max(1, min(x.mb, (int)(allowed / ng[g]))));
                }
            }
        }
        skip_sweep = gap_improved && (i128)best.time * 100 <= busy * x.mb * 108;
        vector<int> preferred;
        auto add_w = [&](int w) {
            if (w >= 1 && w <= x.mb && all_w.count(w) &&
                find(preferred.begin(), preferred.end(), w) == preferred.end()) {
                preferred.push_back(w);
            }
        };
        for (int w : {x.mb, anchor.G, 2 * anchor.G, anchor.G - 1, anchor.G + 1, 2 * anchor.G - 1,
                      2 * anchor.G + 1}) {
            add_w(w);
        }
        for (auto [num, den] : vector<pair<int, int>>{{1, 1},
                                                      {2, 3},
                                                      {1, 2},
                                                      {1, 3},
                                                      {1, 4},
                                                      {1, 5},
                                                      {1, 6},
                                                      {1, 8},
                                                      {1, 12},
                                                      {1, 16},
                                                      {1, 24},
                                                      {1, 32}}) {
            add_w(x.mb * num / den);
        }
        for (int w : {32, 24, 16, 12, 8, 6, 4, 3, 2, 1}) {
            add_w(w);
        }
        for (int w : all_w) {
            add_w(w);
        }
        vector<int> wins = preferred;
        const int priority_variants[] = {4, 5, 0};
        if (!skip_sweep) {
            for (int vi : priority_variants) {
                for (int w : wins) {
                    for (int gap : {0, 1}) {
                        run(w, vi, true, gap, 0, 0, 0, false);
                    }
                }
            }
        }
        // Try the most useful alternative topologies and priority mode after every window has had
        // its early pass.
        if (!skip_sweep && (!list_deep || list_deep_topos)) {
            for (int vi : {1, 2, 3, 6, 7}) {
                for (int w : wins) {
                    run(w, vi, true, 0, 0, 0, 0, false);
                }
            }
        }
        if (!skip_sweep && (!list_deep || list_deep_topos)) {
            for (int vi = 0; vi < 8; vi++) {
                for (int w : wins) {
                    run(w, vi, false, 0, 0, 0, 0, false);
                }
            }
        }
        int chosen_w = plain_time < search_limits::kInfiniteTime
                           ? plain_w
                           : x.mb;  // best safe unboosted list schedule
        set<int> fss, fms = {x.mb, max(1, x.mb / 2), max(1, x.mb / 4)};
        for (int fs : {1, 2, max(1, x.mb / 4), max(1, x.mb / 2), anchor.G}) {
            fss.insert(min(fs, anchor.G));
        }
        vector<int> ratios = {5, 10, 20, 50, 100};
        if (!skip_sweep && !list_deep_topos &&
            (x.mb <= search_limits::kWindowExhaustiveMicrobatchLimit ||
             (long double)x.mb <= 1.2L * anchor.G ||
             (long double)base_time / max((long double)1, (long double)busy * x.mb) > 1.25L)) {
            vector<int> boost_ws;
            if (list_deep) {
                for (int w : preferred) {
                    if (find(boost_ws.begin(), boost_ws.end(), w) == boost_ws.end()) {
                        boost_ws.push_back(w);
                    }
                }
            } else {
                boost_ws.push_back(chosen_w);
            }
            for (int w : boost_ws) {
                for (int vi : {4, 5}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                run(w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r, true);
                            }
                        }
                    }
                }
            }
            if (!list_deep) {
                for (int vi : {4, 5}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                run(chosen_w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r,
                                    false);
                            }
                        }
                    }
                }
                for (int vi : {0, 1, 2, 3, 6, 7}) {
                    for (int fs : fss) {
                        for (int fm : fms) {
                            for (int r : ratios) {
                                for (bool ramp : {true, false}) {
                                    run(chosen_w, vi, true, 0, min(fs, anchor.G), min(fm, x.mb), r,
                                        ramp);
                                }
                            }
                        }
                    }
                }
            }
        }
        cerr << "LIST_V7 anchor=" << to_decimal(base_time) << " plain="
             << (plain_time < search_limits::kInfiniteTime ? to_decimal(plain_time) : "none")
             << " plainW=" << plain_w << " best=" << to_decimal(best.time) << " W=" << best_w
             << " mode=" << best_mode << " variant=" << best_variant << " gap=" << best_gap
             << " boost=" << best_boost_value << " fs=" << best_fs << " fm=" << best_fm
             << " ratio10=" << best_ratio << " ramp=" << best_ramp << " cutoff=" << list_cutoff
             << " main_seconds="
             << chrono::duration<double>(chrono::steady_clock::now() - main_start).count()
             << " checked=closed-interval\n";
    }
    return best;
}

}  // namespace solver
// END MODULE: src/search/list_search.cpp
// END TRANSLATION UNIT: src/search/list_search.cpp
// BEGIN TRANSLATION UNIT: src/search/wave_search.cpp
// BEGIN MODULE: src/search/wave_search.cpp
// Scale-v8 wave strategy and validation.
namespace solver {
using namespace std;
void run_scale_v8_search(const InputData& x, const vector<PartitionCandidate>& pcs,
                         const ScheduleResult& v7_incumbent, ScheduleResult& best, bool serial,
                         bool do_wave, chrono::steady_clock::time_point main_start,
                         chrono::steady_clock::time_point deadline) {
    const auto wave_deadline =
        min(main_start + chrono::milliseconds(search_limits::kWaveDeadlineMs), deadline);
    vector<ScheduleResult> scale_alt_seeds;
    if (!serial && do_wave && x.mb <= search_limits::kExtraLayoutMicrobatchLimit &&
        (i128)x.mb * x.L * operation::kCount <= search_limits::kExtraLayoutNodeLimit &&
        x.L > best.G &&
        chrono::steady_clock::now() - main_start <
            chrono::milliseconds(search_limits::kWaveWarmupMs) &&
        chrono::steady_clock::now() < wave_deadline) {
        const int incumbent_p = best.c.P;
        vector<int> order(pcs.size());
        iota(order.begin(), order.end(), 0);
        sort(order.begin(), order.end(),
             [&](int a, int b) { return pcs[a].probe_time < pcs[b].probe_time; });
        int used = 0;
        auto alt_deadline = wave_deadline;
        for (int pi : order) {
            const Candidate& c = pcs[pi].best_v.P ? pcs[pi].best_v : pcs[pi].max_v;
            if (!c.P || c.P == incumbent_p) {
                continue;
            }
            if (used >= 2 || chrono::steady_clock::now() +
                                     chrono::milliseconds(search_limits::kWaveExtensionReserveMs) >=
                                 alt_deadline) {
                break;
            }
            auto d_alt = compute_durations(x, c);
            int max_v = max(1, min({x.L, search_limits::kMaximumPartitionCount, x.N * x.S / c.P}));
            i128 max_c = 0, max_n = 0, total_c = 0, total_n = 0;
            for (int l = 0; l < x.L; l++) {
                i128 C = 0, N = 0;
                for (int o = 0; o < operation::kCount; o++) {
                    (list_sched::comm(o) ? N : C) += d_alt[l][o];
                }
                max_c = max(max_c, C);
                max_n = max(max_n, N);
                total_c += C;
                total_n += N;
            }
            i128 lb =
                max({(i128)x.mb * max_c, (i128)x.mb * max_n, ceil_div((i128)x.mb * total_c, max_v),
                     ceil_div((i128)x.mb * total_n, max_v)});
            if (lb >= best.time) {
                continue;
            }
            ++used;
            ScheduleResult alt = evaluate_layouts(x, c, true, true, alt_deadline);
            if (alt.ops.empty()) {
                continue;
            }
            scale_alt_seeds.push_back(alt);
            if (alt.time < best.time) {
                cerr << "SCALE_ALT_P oldP=" << best.c.P << " newP=" << alt.c.P
                     << " old=" << to_decimal(best.time) << " new=" << to_decimal(alt.time)
                     << " LB=" << to_decimal(lb) << "\n";
                best = alt;
            }
        }
    }
    if (!serial && do_wave) {
        vector<ScheduleResult> scale_seeds;
        scale_seeds.push_back(v7_incumbent);
        for (auto& alt : scale_alt_seeds) {
            scale_seeds.push_back(alt);
        }
        for (ScheduleResult anchor : scale_seeds) {
            if (chrono::steady_clock::now() >= wave_deadline) {
                break;
            }
            ScheduleResult saved_best = best;
            best = anchor;
            const auto wave_start = chrono::steady_clock::now();
            auto dur = compute_durations(x, anchor.c);
            vector<int> ng(anchor.G);
            for (int g : anchor.group) {
                ng[g]++;
            }
            auto safe_wave = [&](const vector<event_sched::Op>& ops, i128& tm) {
                int stride = x.L * operation::kCount, N = x.mb * stride;
                vector<i128> st(N, -1), en(N, -1);
                tm = 0;
                for (auto& o : ops) {
                    int id = (o.mb * x.L + o.l) * operation::kCount + o.op;
                    st[id] = o.start;
                    en[id] = o.start + dur[o.l][o.op];
                    tm = max(tm, en[id]);
                }
                for (int i = 0; i < N; i++) {
                    if (st[i] < 0) {
                        return false;
                    }
                }
                auto peak = [](vector<pair<i128, i128>>& a) {
                    sort(a.begin(), a.end());
                    multiset<i128> ends;
                    int best = 0;
                    for (size_t i = 0; i < a.size();) {
                        size_t j = i;
                        while (j < a.size() && a[j].first == a[i].first) {
                            j++;
                        }
                        while (!ends.empty() && *ends.begin() < a[i].first) {
                            ends.erase(ends.begin());
                        }
                        best = max(best, (int)ends.size() + (int)(j - i));
                        for (size_t k = i; k < j; k++) {
                            ends.insert(a[k].second);
                        }
                        i = j;
                    }
                    return best;
                };
                for (int g = 0; g < anchor.G; g++) {
                    i128 mexp = (i128)ng[g] * ((x.E / anchor.c.P) * x.Z + x.Zs);
                    vector<pair<i128, i128>> acts, comms;
                    for (int l = 0; l < x.L; l++) {
                        if (anchor.group[l] == g) {
                            for (int m = 0; m < x.mb; m++) {
                                int b = (m * x.L + l) * operation::kCount;
                                acts.push_back(
                                    {en[b + operation::index(operation::kCombineForward)],
                                     st[b + operation::index(operation::kSharedBackward)]});
                                for (int o : operation::kCommunicationOperations) {
                                    if (dur[l][o] > 0) {
                                        comms.push_back({st[b + o], en[b + o]});
                                    }
                                }
                            }
                        }
                    }
                    if (mexp + x.U * peak(comms) + x.Ua * peak(acts) > x.M) {
                        return false;
                    }
                }
                return true;
            };
            struct Trial {
                i128 tm;
                int mode, A, B, phase, pn, pd, W, head, desc, dw;
            };
            vector<Trial> top;
            Trial winner{anchor.time, 0, 0, 0, 0, 0, 0, x.mb, 0, 0, 0};
            auto run_wave = [&](int mode, int A, int B, int phase, int pn, int pd, int head,
                                bool desc, int dw, int W) {
                if (chrono::steady_clock::now() > wave_deadline) {
                    return;
                }
                vector<event_sched::Op> ops;
                i128 tm;
                scheduling::ProblemView problem{x.mb, x.L, anchor.G, anchor.group, dur, ng};
                scheduling::Scheduler<scheduling::ListScheduleStrategy> scheduler(problem);
                scheduling::ListConfig config;
                config.window = W;
                config.rank_mode = mode;
                config.rank_a = A;
                config.rank_b = B;
                config.phase = phase;
                config.pitch_numerator = pn;
                config.pitch_denominator = pd;
                config.duration_head = head;
                config.microbatch_descending = desc;
                config.weight_gradient_order = dw;
                config.fill_gaps = true;
                scheduling::ScheduleOutput output{ops, tm};
                if (!scheduler.run(config, output)) {
                    return;
                }
                i128 checked;
                if (!safe_wave(ops, checked)) {
                    return;
                }
                if (W == x.mb) {
                    Trial t{checked, mode, A, B, phase, pn, pd, W, head, 0, dw};
                    top.push_back(t);
                    sort(top.begin(), top.end(), [](auto& a, auto& b) { return a.tm < b.tm; });
                    if (top.size() > 2) {
                        top.pop_back();
                    }
                }
                if (checked < best.time) {
                    winner = {checked, mode, A, B, phase, pn, pd, W, head, 0, dw};
                    sort(ops.begin(), ops.end(), [](auto& a, auto& b) {
                        return tie(a.start, a.mb, a.l, a.op) < tie(b.start, b.mb, b.l, b.op);
                    });
                    best.time = checked;
                    best.ops = move(ops);
                }
            };
            vector<int> pitches = {1, 2, 4};
            run_wave(1, 2, 1, 0, 1, 1, 0, false, 0, x.mb);
            for (int pn : pitches) {
                for (int head : {1, 2}) {
                    run_wave(2, 1, 1, 0, pn, 4, head, false, 0, x.mb);
                }
            }
            run_wave(2, 1, 1, 0, 2, 4, 2, false, 1, x.mb);
            run_wave(2, 1, 1, 0, 2, 4, 2, false, 2, x.mb);
            vector<int> ws = {anchor.G, 2 * anchor.G, max(1, x.mb / 2), x.mb};
            sort(ws.begin(), ws.end());
            ws.erase(unique(ws.begin(), ws.end()), ws.end());
            for (size_t i = 0; i < top.size() && i < 2; i++) {
                for (int w : ws) {
                    if (w != x.mb) {
                        auto t = top[i];
                        run_wave(t.mode, t.A, t.B, t.phase, t.pn, t.pd, t.head, t.desc, t.dw, w);
                    }
                }
            }
            cerr << "WAVE_V8 anchor=" << to_decimal(anchor.time)
                 << " best=" << to_decimal(best.time)
                 << " improvement=" << to_decimal(anchor.time - best.time)
                 << " mode=" << winner.mode << " A=" << winner.A << " B=" << winner.B
                 << " phase=" << winner.phase << " pitch=" << winner.pn << "/" << winner.pd
                 << " head="
                 << (winner.head == 1   ? "ES"
                     : winner.head == 2 ? "EF"
                                        : "layerMean")
                 << " dw=" << winner.dw << " W=" << winner.W << " top=" << top.size() << " elapsed="
                 << chrono::duration<double>(chrono::steady_clock::now() - wave_start).count()
                 << " total="
                 << chrono::duration<double>(chrono::steady_clock::now() - main_start).count()
                 << "\n";
            ScheduleResult wave_result = best;
            best = move(saved_best);
            if (wave_result.time < best.time) {
                best = move(wave_result);
            }
        }
    }
}

}  // namespace solver
// END MODULE: src/search/wave_search.cpp
// END TRANSLATION UNIT: src/search/wave_search.cpp
// BEGIN TRANSLATION UNIT: src/search/local_engine_polish.cpp
// BEGIN MODULE: src/search/local_engine_polish.cpp
// BEGIN MODULE: src/search/local_engine_polish.hpp
namespace local_engine_polish {
using i128 = __int128_t;
struct Stats {
    long long evaluated = 0, accepted = 0, strict_improve = 0, tie_moves = 0;
    int memory_fast_groups = 0;
    int rounds = 0;
    bool exhausted = true;
};
bool polish(int mb, int L, int G, const std::vector<int>& group,
            const std::vector<std::array<i128, operation::kCount>>& dur,
            const std::vector<event_sched::Op>& input, i128 memory, i128 U, i128 Ua,
            i128 resident_per_layer, std::vector<event_sched::Op>& output, i128& best_time,
            Stats& stats, std::chrono::steady_clock::time_point deadline,
            long long eval_limit = 12000, int pass = 0, bool retime_auto = true);
}  // namespace local_engine_polish
// END MODULE: src/search/local_engine_polish.hpp

// ===== local_engine_polish =====

namespace local_engine_polish {
namespace limits {
inline constexpr int kOuterDeadlineCheckMask = 31;
inline constexpr int kInnerDeadlineCheckMask = 255;
inline constexpr int kBlockLengthMin = 4;
inline constexpr int kBlockLengthMax = 7;
inline constexpr int kVariantCycle = 4;
inline constexpr int kDistanceRotationMultiplier = 7;
inline constexpr int kResourceRotationMultiplier = 13;
inline constexpr int kOperationRotationMultiplier = 37;
inline constexpr int kPermutationStartMultiplier = 997;
inline constexpr int kPermutationWindowStride = 37;
inline constexpr int kDistanceRotationSpan = 8;
inline constexpr int kVariantDistanceStep0 = 12;
inline constexpr int kVariantDistanceStep1 = 16;
inline constexpr int kVariantDistanceStep2 = 24;
inline constexpr int kVariantDistanceStep3 = 32;
}  // namespace limits
using i128 = __int128_t;

inline int engine(int o) {
    return (o == operation::kDispatchForward || o == operation::kCombineForward ||
            o == operation::kCombineBackward || o == operation::kDispatchBackward)
               ? operation::kCommunicationEngine
               : operation::kComputeEngine;
}
inline int id(int m, int l, int o, int L) {
    return operation_graph::node_id(m, l, o, L);
}

// Fixed-layout local search. Each positive-duration operation occupies exactly
// one (group, engine) sequence. DAG and resource constraints are retimed by a
// longest-path pass after each trial ordering.
bool polish(int mb, int L, int G, const std::vector<int>& group,
                   const std::vector<std::array<i128, operation::kCount>>& dur,
                   const std::vector<event_sched::Op>& input, i128 M, i128 U, i128 Ua,
                   i128 resident_per_layer, std::vector<event_sched::Op>& output, i128& best_time,
                   Stats& stats, std::chrono::steady_clock::time_point deadline,
                   long long max_evaluations, int variant, bool retime_auto) {
    if (std::chrono::steady_clock::now() >= deadline) {
        output = input;
        return true;
    }
    output = input;
    const int n = mb * L * operation::kCount;
    if ((int)input.size() != n) {
        return false;
    }
    std::vector<i128> node_duration(n);
    std::vector<long long> node_duration64(n);
    const i128 max_i64 = std::numeric_limits<long long>::max();
    i128 positive_duration_sum = 0;
    bool duration_sum_fits = true;
    for (int m = 0; m < mb; m++) {
        for (int l = 0; l < L; l++) {
            for (int o = 0; o < operation::kCount; o++) {
                int u = id(m, l, o, L);
                node_duration[u] = dur[l][o];
                if (dur[l][o] > 0) {
                    if (dur[l][o] > max_i64 - positive_duration_sum) {
                        duration_sum_fits = false;
                    } else if (duration_sum_fits) {
                        positive_duration_sum += dur[l][o];
                    }
                }
            }
        }
    }
    const i128 path_bound = positive_duration_sum + n;
    const bool sum_end_fits = path_bound <= max_i64 && (i128)n <= max_i64 / path_bound;
    bool int64_safe = retime_auto && duration_sum_fits && path_bound <= max_i64 && sum_end_fits &&
                      best_time >= 0 && best_time <= max_i64;
    if (int64_safe) {
        for (int u = 0; u < n; u++) {
            if (node_duration[u] < 0 || node_duration[u] > max_i64) {
                int64_safe = false;
                break;
            }
            node_duration64[u] = (long long)node_duration[u];
        }
    }
    std::vector<std::pair<int, int>> base_edges;
    auto edge = [&](int a, int b) { base_edges.push_back({a, b}); };
    for (int m = 0; m < mb; m++) {
        if ((m & limits::kOuterDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        for (int l = 0; l < L; l++) {
            operation_graph::append_layer_edges(
                m, l, L, [L](int mm, int ll, int op) { return id(mm, ll, op, L); }, edge);
        }
    }
    std::vector<i128> orig(n);
    for (auto& o : input) {
        orig[id(o.mb, o.l, o.op, L)] = o.start;
    }
    using Key = std::pair<int, int>;
    std::map<Key, std::vector<int>> seq;
    for (int m = 0; m < mb; m++) {
        if ((m & limits::kOuterDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        for (int l = 0; l < L; l++) {
            for (int o = 0; o < operation::kCount; o++) {
                if (dur[l][o] > 0) {
                    seq[{group[l], engine(o)}].push_back(id(m, l, o, L));
                }
            }
        }
    }
    for (auto& kv : seq) {
        std::sort(kv.second.begin(), kv.second.end(),
                  [&](int a, int b) { return std::tie(orig[a], a) < std::tie(orig[b], b); });
    }
    std::vector<std::vector<int>> base_out(n);
    std::vector<int> base_indegree(n, 0);
    for (auto [a, b] : base_edges) {
        base_out[a].push_back(b);
        base_indegree[b]++;
    }
    // Exact official closed-interval resource and memory legality check.
    std::vector<unsigned char> memory_always_ok(G, 1);
    for (int g = 0; g < G; g++) {
        int layers = 0;
        for (int l = 0; l < L; l++) {
            layers += (group[l] == g);
        }
        i128 comm_upper = 0;
        for (int l = 0; l < L; l++) {
            if (group[l] == g) {
                for (int o : operation::kCommunicationOperations) {
                    comm_upper = std::max(comm_upper, dur[l][o]);
                }
            }
        }
        i128 fixed_upper = (i128)layers * resident_per_layer +
                           operation::kMaxCommunicationBuffers * U + (i128)layers * mb * Ua;
        if (comm_upper == 0) {
            fixed_upper -= operation::kMaxCommunicationBuffers * U;
        }
        memory_always_ok[g] = fixed_upper <= M;
        stats.memory_fast_groups += memory_always_ok[g];
    }
    bool memory_all_fast = stats.memory_fast_groups == G;
    auto memory_ok = [&](const auto& st, const auto& en) {
        // Closed intervals overlap when one reservation ends exactly as another begins.
        auto peak_closed = [](std::vector<std::pair<i128, i128>>& a) {
            std::sort(a.begin(), a.end());
            std::multiset<i128> ends;
            int best = 0;
            for (size_t i = 0; i < a.size();) {
                size_t j = i;
                while (j < a.size() && a[j].first == a[i].first) {
                    j++;
                }
                while (!ends.empty() && *ends.begin() < a[i].first) {
                    ends.erase(ends.begin());
                }
                best = std::max(best, (int)ends.size() + (int)(j - i));
                for (size_t k = i; k < j; k++) {
                    ends.insert(a[k].second);
                }
                i = j;
            }
            return best;
        };
        for (int g = 0; g < G; g++) {
            if (memory_always_ok[g]) {
                continue;
            }
            int layers = 0;
            for (int l = 0; l < L; l++) {
                layers += (group[l] == g);
            }
            std::vector<std::pair<i128, i128>> acts, comms;
            for (int m = 0; m < mb; m++) {
                for (int l = 0; l < L; l++) {
                    if (group[l] == g) {
                        int b = id(m, l, 0, L);
                        acts.push_back({en[b + operation::kCombineForward],
                                        st[b + operation::kSharedBackward]});
                        for (int o : operation::kCommunicationOperations) {
                            if (dur[l][o] > 0) {
                                comms.push_back({st[b + o], en[b + o]});
                            }
                        }
                    }
                }
            }
            i128 used =
                (i128)layers * resident_per_layer + U * peak_closed(comms) + Ua * peak_closed(acts);
            if (used > M) {
                return false;
            }
        }
        return true;
    };
    auto run_typed = [&](const std::map<Key, std::vector<int>>& s, int gap,
                         std::vector<event_sched::Op>& cand, auto& tm, auto& sum_end,
                         auto best_secondary, const auto& duration) -> bool {
        std::vector<int> indeg = base_indegree, next(n, -1);
        std::vector<unsigned char> next_gap(n, 0);
        for (auto& kv : s) {
            auto& v = kv.second;
            int w = (kv.first.second == operation::kCommunicationEngine ? gap : 0);
            for (size_t j = 1; j < v.size(); j++) {
                next[v[j - 1]] = v[j];
                next_gap[v[j - 1]] = (unsigned char)w;
                indeg[v[j]]++;
            }
        }
        std::vector<int> q;
        q.reserve(n);
        for (int i = 0; i < n; i++) {
            if (!indeg[i]) {
                q.push_back(i);
            }
        }
        using Time = std::decay_t<decltype(tm)>;
        const Time time_limit = static_cast<Time>(best_time);
        std::vector<Time> st(n, 0), en(n, 0);
        int done = 0;
        tm = 0;
        sum_end = 0;
        for (size_t qi = 0; qi < q.size(); qi++) {
            if ((qi & limits::kInnerDeadlineCheckMask) == 0 &&
                std::chrono::steady_clock::now() >= deadline) {
                return false;
            }
            int u = q[qi];
            done++;
            en[u] = st[u] + duration[u];
            tm = std::max(tm, en[u]);
            if (tm > time_limit) {
                return false;
            }
            sum_end += en[u];
            for (int v : base_out[u]) {
                st[v] = std::max(st[v], en[u]);
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
            int v = next[u];
            if (v >= 0) {
                st[v] = std::max(st[v], en[u] + next_gap[u]);
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
        }
        if (done != n) {
            return false;
        }
        // Local polish alone permits equal Time when the secondary sum of end times falls.
        if (tm > time_limit || (tm == time_limit && sum_end >= best_secondary)) {
            return false;
        }
        if (!memory_ok(st, en)) {
            return false;
        }
        cand.clear();
        cand.reserve(n);
        for (int m = 0; m < mb; m++) {
            for (int l = 0; l < L; l++) {
                for (int o = 0; o < operation::kCount; o++) {
                    cand.push_back({st[id(m, l, o, L)], m, l, o});
                }
            }
        }
        std::sort(cand.begin(), cand.end(), [](auto& a, auto& b) {
            return std::tie(a.start, a.mb, a.l, a.op) < std::tie(b.start, b.mb, b.l, b.op);
        });
        return true;
    };
    auto run = [&](const std::map<Key, std::vector<int>>& s, int gap,
                   std::vector<event_sched::Op>& cand, i128& tm, i128& sum_end,
                   i128 best_secondary) -> bool {
        if (int64_safe && best_secondary >= 0 && best_secondary <= max_i64) {
            long long t64 = 0, sum64 = 0;
            bool ok =
                run_typed(s, gap, cand, t64, sum64, (long long)best_secondary, node_duration64);
            tm = t64;
            sum_end = sum64;
            return ok;
        }
        return run_typed(s, gap, cand, tm, sum_end, best_secondary, node_duration);
    };

    // Retiming current ordering for each candidate gap; only use it if legal and
    // faster. Try one gap first, then exact block enumeration on the critical path.
    std::map<Key, std::vector<int>> best_seq = seq;
    i128 resource_lb = 0;
    for (auto& kv : best_seq) {
        i128 load = 0;
        for (int z : kv.second) {
            load += dur[operation_graph::layer_of(z, L)][operation_graph::operation_of(z)];
        }
        resource_lb = std::max(resource_lb, load);
    }
    std::vector<event_sched::Op> cand;
    i128 tm, sum_end;
    int chosen_gap = 0;
    i128 best_secondary = 0;
    for (auto& o : input) {
        best_secondary += o.start + dur[o.l][o.op];
    }
    for (int gap = 0; gap <= (variant > 0 && memory_all_fast ? 0 : 1); gap++) {
        if (std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        bool ok = run(best_seq, gap, cand, tm, sum_end, best_secondary);
        stats.evaluated++;
        if (ok) {
            if (tm < best_time) {
                best_time = tm;
                stats.strict_improve++;
            } else {
                stats.tie_moves++;
            }
            best_secondary = sum_end;
            output = cand;
            chosen_gap = gap;
            stats.accepted++;
        }
    }
    // Find a longest path in the reusable base DAG plus current resource chains.
    std::vector<int> indeg = base_indegree, next(n, -1);
    std::vector<unsigned char> next_gap(n, 0);
    for (auto& kv : best_seq) {
        auto& v = kv.second;
        int w = (kv.first.second == operation::kCommunicationEngine ? chosen_gap : 0);
        for (size_t j = 1; j < v.size(); j++) {
            next[v[j - 1]] = v[j];
            next_gap[v[j - 1]] = (unsigned char)w;
            indeg[v[j]]++;
        }
    }
    std::vector<int> topo;
    {
        std::vector<int> q;
        q.reserve(n);
        for (int i = 0; i < n; i++) {
            if (!indeg[i]) {
                q.push_back(i);
            }
        }
        for (size_t qi = 0; qi < q.size(); qi++) {
            if ((qi & limits::kInnerDeadlineCheckMask) == 0 &&
                std::chrono::steady_clock::now() >= deadline) {
                return true;
            }
            int u = q[qi];
            topo.push_back(u);
            for (int v : base_out[u]) {
                if (--indeg[v] == 0) {
                    q.push_back(v);
                }
            }
            int v = next[u];
            if (v >= 0 && --indeg[v] == 0) {
                q.push_back(v);
            }
        }
    }
    if ((int)topo.size() != n) {
        return true;
    }
    std::vector<i128> start(n, 0), finish(n, 0);
    std::vector<int> par(n, -1);
    for (int u : topo) {
        if ((u & limits::kInnerDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        int l = operation_graph::layer_of(u, L), o = operation_graph::operation_of(u);
        finish[u] = start[u] + dur[l][o];
        for (int v : base_out[u]) {
            i128 ns = finish[u];
            if (ns > start[v]) {
                start[v] = ns, par[v] = u;
            }
        }
        int v = next[u];
        if (v >= 0) {
            i128 ns = finish[u] + next_gap[u];
            if (ns > start[v]) {
                start[v] = ns, par[v] = u;
            }
        }
    }
    int end = 0;
    for (int u = 1; u < n; u++) {
        if (finish[u] > finish[end]) {
            end = u;
        }
    }
    std::vector<int> cp;
    for (int u = end; u >= 0; u = par[u]) {
        cp.push_back(u);
    }
    std::reverse(cp.begin(), cp.end());
    std::map<int, std::map<Key, std::vector<int>>> windows;
    for (size_t i = 0; i < cp.size();) {
        if ((i & limits::kInnerDeadlineCheckMask) == 0 &&
            std::chrono::steady_clock::now() >= deadline) {
            return true;
        }
        int u = cp[i], l = operation_graph::layer_of(u, L), o = operation_graph::operation_of(u);
        if (dur[l][o] <= 0) {
            i++;
            continue;
        }
        Key k = {group[l], engine(o)};
        size_t j = i + 1;
        while (j < cp.size()) {
            int v = cp[j];
            int vl = operation_graph::layer_of(v, L), vo = operation_graph::operation_of(v);
            if (dur[vl][vo] <= 0 || Key{group[vl], engine(vo)} != k) {
                break;
            }
            j++;
        }
        auto it = best_seq.find(k);
        if (it != best_seq.end()) {
            std::map<int, int> pos;
            for (int p = 0; p < (int)it->second.size(); p++) {
                pos[it->second[p]] = p;
            }
            int lo = it->second.size(), hi = -1;
            for (size_t z = i; z < j; z++) {
                lo = std::min(lo, pos[cp[z]]);
                hi = std::max(hi, pos[cp[z]]);
            }
            for (int a = lo; a <= hi; a++) {
                for (int len = limits::kBlockLengthMin;
                     len <= limits::kBlockLengthMax && a + len <= hi + 1; len++) {
                    windows[len][k].push_back(a);
                }
            }
        }
        i = j;
    }
    // Try insertion moves first, interleaving resources and move distances.
    std::set<int> critical(cp.begin(), cp.end());
    auto try_seq = [&]() {
        if (resource_lb > best_time) {
            return;
        }
        for (int gap = 0; gap <= (variant > 0 && memory_all_fast ? 0 : 1); gap++) {
            if (stats.evaluated >= max_evaluations ||
                std::chrono::steady_clock::now() >= deadline) {
                stats.exhausted = false;
                return;
            }
            std::vector<event_sched::Op> cc;
            i128 t, s;
            bool ok = run(best_seq, gap, cc, t, s, best_secondary);
            stats.evaluated++;
            if (ok) {
                if (t < best_time) {
                    best_time = t;
                    stats.strict_improve++;
                } else {
                    stats.tie_moves++;
                }
                best_secondary = s;
                output.swap(cc);
                chosen_gap = gap;
                stats.accepted++;
            }
        }
    };
    auto insertion_base = best_seq;
    std::map<Key, std::vector<int>> critical_by_resource;
    for (auto& kv : insertion_base) {
        for (int z : kv.second) {
            if (critical.count(z)) {
                critical_by_resource[kv.first].push_back(z);
            }
        }
    }
    std::vector<int> distances, dirs;
    for (int d = 1; d <= limits::kDistanceRotationSpan; d++) {
        distances.push_back(d);
    }
    dirs = {-1, 1};
    if (variant > 0) {
        for (int d : {limits::kVariantDistanceStep0, limits::kVariantDistanceStep1,
                      limits::kVariantDistanceStep2, limits::kVariantDistanceStep3}) {
            distances.push_back(d);
        }
        std::rotate(distances.begin(),
                    distances.begin() +
                        ((variant * limits::kDistanceRotationMultiplier) % distances.size()),
                    distances.end());
        if (variant % 2) {
            std::reverse(dirs.begin(), dirs.end());
        }
    }
    std::vector<Key> resources;
    for (auto& kr : critical_by_resource) {
        resources.push_back(kr.first);
    }
    if (!resources.empty() && variant > 0) {
        std::rotate(resources.begin(),
                    resources.begin() +
                        ((variant * limits::kResourceRotationMultiplier) % resources.size()),
                    resources.end());
    }
    if (variant > 0) {
        for (auto& kr : critical_by_resource) {
            auto& ops = kr.second;
            if (!ops.empty()) {
                std::rotate(
                    ops.begin(),
                    ops.begin() + ((variant * limits::kOperationRotationMultiplier) % ops.size()),
                    ops.end());
                if (variant % 2) {
                    std::reverse(ops.begin(), ops.end());
                }
            }
        }
    }
    for (int distance : distances) {
        if (variant > 0 && variant % limits::kVariantCycle == 0) {
            break;
        }
        if (!stats.exhausted) {
            break;
        }
        for (int dir : dirs) {
            for (const auto& resource : resources) {
                auto& kr = *critical_by_resource.find(resource);
                for (int z : kr.second) {
                    if (!stats.exhausted) {
                        break;
                    }
                    auto& w = best_seq[kr.first];
                    auto itp = std::find(w.begin(), w.end(), z);
                    if (itp == w.end()) {
                        continue;
                    }
                    int p = itp - w.begin(), q = p + dir * distance;
                    if (q < 0 || q >= (int)w.size()) {
                        continue;
                    }
                    auto old = w;
                    w.erase(w.begin() + p);
                    w.insert(w.begin() + q, z);
                    long long before = stats.accepted;
                    try_seq();
                    if (stats.accepted == before) {
                        w.swap(old);
                    }
                }
            }
        }
    }
    // For each block size, spread the first pass across all resources before
    // completing additional windows. Each window enumerates every permutation.
    std::vector<int> lengths;
    for (int len = limits::kBlockLengthMin; len <= limits::kBlockLengthMax; ++len) {
        lengths.push_back(len);
    }
    if (variant > 0) {
        std::rotate(lengths.begin(), lengths.begin() + ((variant / 4) % lengths.size()),
                    lengths.end());
    }
    auto unrank_permutation = [](std::vector<int> items, size_t rank) {
        std::vector<int> result;
        result.reserve(items.size());
        for (size_t left = items.size(); left > 0; left--) {
            size_t factorial = 1;
            for (size_t k = 2; k < left; k++) {
                factorial *= k;
            }
            size_t index = rank / factorial;
            rank %= factorial;
            result.push_back(items[index]);
            items.erase(items.begin() + index);
        }
        return result;
    };
    for (int len : lengths) {
        if (!stats.exhausted) {
            break;
        }
        auto wit = windows.find(len);
        if (wit == windows.end()) {
            continue;
        }
        auto& by_resource = wit->second;
        size_t max_windows = 0;
        for (auto& kv : by_resource) {
            max_windows = std::max(max_windows, kv.second.size());
        }
        std::vector<Key> window_resources;
        for (auto& kv : by_resource) {
            window_resources.push_back(kv.first);
        }
        if (variant > 0) {
            for (auto& kv : by_resource) {
                if (!kv.second.empty()) {
                    std::rotate(kv.second.begin(), kv.second.begin() + (variant % kv.second.size()),
                                kv.second.end());
                }
            }
            if (!window_resources.empty()) {
                std::rotate(window_resources.begin(),
                            window_resources.begin() +
                                ((variant * limits::kResourceRotationMultiplier + len) %
                                 window_resources.size()),
                            window_resources.end());
            }
        }
        for (size_t wi = 0; wi < max_windows && stats.exhausted; wi++) {
            for (const Key& resource : window_resources) {
                auto& kv = *by_resource.find(resource);
                if (wi >= kv.second.size()) {
                    continue;
                }
                int a = kv.second[wi];
                if (stats.evaluated >= max_evaluations ||
                    std::chrono::steady_clock::now() >= deadline) {
                    stats.exhausted = false;
                    break;
                }
                auto it = best_seq.find(kv.first);
                if (it == best_seq.end() || a + len > (int)it->second.size()) {
                    continue;
                }
                auto& v = it->second;
                auto block = std::vector<int>(v.begin() + a, v.begin() + a + len);
                auto sorted = block;
                std::sort(sorted.begin(), sorted.end());
                size_t permutation_count = 1;
                for (int k = 2; k <= len; k++) {
                    permutation_count *= k;
                }
                size_t start_rank = 0;
                if (variant > 0) {
                    start_rank = ((size_t)variant * limits::kPermutationStartMultiplier +
                                  wi * limits::kPermutationWindowStride + (size_t)a) %
                                 permutation_count;
                }
                auto start_perm = variant > 0 ? unrank_permutation(sorted, start_rank) : sorted;
                auto perm = start_perm;
                auto accepted_block = block;
                do {
                    if (perm != block) {
                        std::copy(perm.begin(), perm.end(), v.begin() + a);
                        long long before = stats.accepted;
                        try_seq();
                        if (stats.accepted > before) {
                            accepted_block = perm;
                        } else {
                            std::copy(accepted_block.begin(), accepted_block.end(), v.begin() + a);
                        }
                    }
                    if (!stats.exhausted) {
                        break;
                    }
                    if (!std::next_permutation(perm.begin(), perm.end())) {
                        perm = sorted;
                    }
                    if (perm == start_perm) {
                        break;
                    }
                } while (true);
                if (!stats.exhausted) {
                    break;
                }
            }
        }
    }

    return true;
}
}  // namespace local_engine_polish
// END MODULE: src/search/local_engine_polish.cpp
// END TRANSLATION UNIT: src/search/local_engine_polish.cpp
// BEGIN TRANSLATION UNIT: src/search/polish_driver.cpp
// BEGIN MODULE: src/search/polish_driver.cpp
// Coordinate bounded local-polish passes and report their results.
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
// END MODULE: src/search/polish_driver.cpp
// END TRANSLATION UNIT: src/search/polish_driver.cpp
