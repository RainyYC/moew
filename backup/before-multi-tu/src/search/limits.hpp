#pragma once

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
inline constexpr int kExtensionDeadlineReserveMs = 30;
inline constexpr int kExtensionIterationBudget = 700;
inline constexpr int kPlacementSearchBudget = 250000;
inline constexpr int kPlacementPeakSearchSteps = 12;
inline constexpr int kMaximumPartitionCount = 64;
inline constexpr long long kMillion = 1000000LL;
inline constexpr long long kTrillion = 1000000000000LL;
inline constexpr __int128_t kInfiniteTime = static_cast<__int128_t>(1) << 126;
}  // namespace solver::search_limits
