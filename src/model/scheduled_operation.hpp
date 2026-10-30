#pragma once
#include "../common.hpp"

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
