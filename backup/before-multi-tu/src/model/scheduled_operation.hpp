#pragma once
#include "../common.hpp"

namespace event_sched {
using i128 = __int128_t;

struct Op {
    i128 start;
    int mb;
    int l;
    int op;
};
}  // namespace event_sched
