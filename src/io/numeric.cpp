#include "numeric.hpp"
// Exact integer parsing, formatting, and arithmetic helpers.
#include "../common.hpp"
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
