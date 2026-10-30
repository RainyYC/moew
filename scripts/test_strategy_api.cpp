#include "../src/scheduling/schedule_api.hpp"

struct TestConfig {
    int expected_layers = 0;
};

struct TestStrategy {
    using Config = TestConfig;

    static bool schedule(const scheduling::ProblemView& problem, const Config& config,
                         scheduling::ScheduleOutput& output) {
        output.operations.clear();
        output.makespan = problem.layers == config.expected_layers ? 17 : -1;
        return output.makespan == 17;
    }
};

int main() {
    std::vector<int> groups{0};
    scheduling::Durations durations(1);
    std::vector<int> group_layers{1};
    scheduling::ProblemView problem{1, 1, 1, groups, durations, group_layers};
    scheduling::Scheduler<TestStrategy> scheduler(problem);
    TestConfig config{1};
    std::vector<solver::ScheduledOperation> operations;
    scheduling::i128 makespan = 0;
    scheduling::ScheduleOutput output{operations, makespan};
    return scheduler.run(config, output) && makespan == 17 ? 0 : 1;
}
