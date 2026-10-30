#include "event_scheduler.hpp"
#include <array>
#include <cassert>
#include <iostream>
#include <vector>

int main() {
    using namespace event_sched;
    const int mb=3,L=2,G=2;
    std::vector<int> group={0,1}, ng={1,1}, A={2,2}, b={2,1};
    std::vector<std::array<i128,10>> d(L);
    for (int l=0;l<L;++l) d[l]={2,1,2,2,1,1,1,3,1,1};
    std::vector<Op> ops; i128 t=0;
    bool ok=schedule(mb,L,G,group,d,ng,A,b,0,ops,t);
    assert(ok && (int)ops.size()==mb*L*10);
    assert(t>0);
    std::vector<std::array<i128,10>> st(mb*L);
    auto verify_dag=[&](const std::vector<Op>& schedule) {
        for (const auto& x:schedule) st[x.mb*L+x.l][x.op]=x.start;
        auto end=[&](int m,int l,int o){return st[m*L+l][o]+d[l][o];};
        for (int m=0;m<mb;++m) for (int l=0;l<L;++l) {
            auto& s=st[m*L+l];
            assert(s[1]>=0 && s[2]>=end(m,l,1) && s[3]>=end(m,l,2));
            assert(s[3]>=end(m,l,0));
            assert(s[4]>=end(m,l,3) && s[5]>=end(m,l,3));
            assert(s[6]>=end(m,l,5) && s[7]>=end(m,l,5) && s[9]>=end(m,l,5));
            assert(s[8]>=end(m,l,6) && s[8]>=end(m,l,4));
            if (l) assert(s[0]>=end(m,l-1,3) && s[1]>=end(m,l-1,3));
            if (l+1<L) assert(s[4]>=end(m,l+1,8) && s[5]>=end(m,l+1,8));
        }
    };
    verify_dag(ops);
    // Verify starts are monotone and each communication engine obeys b_g.
    for (size_t i=1;i<ops.size();++i) assert(ops[i-1].start<=ops[i].start);
    for (int g=0;g<G;++g) {
        bool have=false; i128 ps=0,pe=0;
        for (const auto& x:ops) if (group[x.l]==g &&
            (x.op==1 || x.op==3 || x.op==5 || x.op==8)) {
            i128 dur=d[x.l][x.op];
            if (have) {
                i128 lo=b[g]==1 ? pe+1 : std::max(pe,ps+1);
                assert(x.start>=lo);
            }
            have=true; ps=x.start; pe=x.start+dur;
        }
    }
    std::vector<Op> ops_b; i128 t_b=0;
    assert(schedule(mb,L,G,group,d,ng,A,b,0,ops_b,t_b,1));
    assert(ops_b.size()==ops.size() && t_b>0);
    verify_dag(ops_b);
    std::vector<Op> ops_c; i128 t_c=0;
    assert(schedule(mb,L,G,group,d,ng,A,b,0,ops_c,t_c,2));
    assert(ops_c.size()==ops.size() && t_c>0);
    verify_dag(ops_c);
    std::vector<Op> ops_d; i128 t_d=0;
    assert(schedule(mb,L,G,group,d,ng,A,b,0,ops_d,t_d,3,1,2,20,false));
    assert(ops_d.size()==ops.size() && t_d>0);
    verify_dag(ops_d);
    std::vector<Op> ops_d0; i128 t_d0=0;
    assert(schedule(mb,L,G,group,d,ng,A,b,0,ops_d0,t_d0,3,1,2,0,false));
    assert(ops_d0.size()==ops.size() && t_d0>0);
    verify_dag(ops_d0);
    // Zero-duration dependency closure must still emit every node.
    for (auto& row:d) row.fill(0);
    ops.clear(); t=0;
    ok=schedule(2,2,2,group,d,ng,A,b,0,ops,t);
    assert(ok && ops.size()==40 && t==0);
    // Mixed group: zero-duration communication is ignored by buffer spacing.
    d[0][1]=0;
    ops.clear(); t=0;
    ok=schedule(2,2,2,group,d,ng,A,b,0,ops,t);
    assert(ok && ops.size()==40);
    std::cout << "event scheduler smoke passed; makespan=" << (long long)t << "\n";
}
