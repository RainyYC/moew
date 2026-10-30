#pragma once
#include "../common.hpp"
namespace solver {
using i128 = __int128_t;
std::istream& operator>>(std::istream& in, i128& v);
inline i128 ceil_div(i128 a, i128 b) {
    return (a + b - 1) / b;
}
std::string to_decimal(i128 x);
}  // namespace solver
