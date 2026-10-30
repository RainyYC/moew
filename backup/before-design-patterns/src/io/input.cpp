#include "input.hpp"
// Input stream parsing into the problem value object.
#include "../model/problem.hpp"
#include "numeric.hpp"
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
