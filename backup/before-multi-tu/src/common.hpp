#pragma once

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
