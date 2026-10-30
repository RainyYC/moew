// Study helper: invoke the exact current make_map implementation for one P.
// The solver itself is not modified and this helper does not schedule work.
#define main included_solver_main
#include "../../solver.cpp"
#undef main

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    int P = atoi(argv[1]);
    In x = read_input();
    i128 cost = 0;
    auto mp = make_map(x, P, cost);
    for (const auto& row : mp) {
        for (size_t e=0; e<row.size(); ++e) {
            if (e) cout << ' ';
            cout << row[e];
        }
        cout << '\n';
    }
    return 0;
}
