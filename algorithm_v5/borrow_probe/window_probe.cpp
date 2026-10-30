#include "../event_scheduler.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

using event_sched::i128;
static std::string str128(i128 x) {
    if (!x) return "0";
    bool neg=x<0; if(neg)x=-x;
    std::string s; while(x){s.push_back(char('0'+x%10));x/=10;}
    if(neg)s.push_back('-'); std::reverse(s.begin(),s.end()); return s;
}
int main(int argc,char**argv){
    if(argc!=3){std::cerr<<"usage: window_probe CONFIG STARTS_OUT\n";return 2;}
    std::ifstream in(argv[1]);if(!in){std::cerr<<"config open failed\n";return 2;}
    int mb,L,G;in>>mb>>L>>G;
    std::vector<int> group(L),ng(G),capAuto(G),bufAuto(G),capOne(G),bufOne(G);
    for(int&x:group)in>>x;for(int&x:ng)in>>x;
    for(int&x:capAuto)in>>x;for(int&x:bufAuto)in>>x;
    for(int&x:capOne)in>>x;for(int&x:bufOne)in>>x;
    std::vector<std::array<i128,10>>dur(L);
    for(auto&row:dur)for(auto&x:row){std::string s;in>>s;x=0;for(char c:s)x=x*10+(c-'0');}
    if(!in){std::cerr<<"malformed config\n";return 2;}
    std::vector<int>windows;
    for(int w=1;w<=std::min(mb,64);++w)windows.push_back(w);
    if(mb>64){for(int d:{3,4,5,6,8,12})windows.push_back(mb/d);windows.push_back(mb);}
    std::sort(windows.begin(),windows.end());windows.erase(std::unique(windows.begin(),windows.end()),windows.end());
    i128 best=((i128)1<<126);std::vector<event_sched::Op>bestOps;
    int bestW=-1,bestMode=-1,bestBuf=-1;double elapsed=0;long long calls=0;
    auto begin=std::chrono::steady_clock::now();
    bool stop=false;
    for(int bset=0;bset<2&&!stop;++bset){
        const auto&caps=bset?capOne:capAuto;const auto&bufs=bset?bufOne:bufAuto;
        for(int mode=0;mode<=2&&!stop;++mode)for(int w:windows){
            elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
            if(elapsed>=10.0){stop=true;break;}
            std::vector<event_sched::Op>ops;i128 tm;
            ++calls;
            if(event_sched::schedule(mb,L,G,group,dur,ng,caps,bufs,w,ops,tm,mode)&&tm<best){
                best=tm;bestW=w;bestMode=mode;bestBuf=bset;bestOps.swap(ops);
            }
        }
    }
    elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
    if(bestW<0){std::cout<<"NO_SCHEDULE calls="<<calls<<" sec="<<elapsed<<"\n";return 1;}
    std::ofstream starts(argv[2]);
    starts<<mb*L*10<<"\n";
    std::vector<i128>byId(mb*L*10,-1);
    for(const auto&o:bestOps)byId[(o.mb*L+o.l)*10+o.op]=o.start;
    for(i128 t:byId)starts<<str128(t)<<"\n";
    std::cout<<"time="<<str128(best)<<" window="<<bestW<<" mode="<<bestMode
             <<" buffers="<<(bestBuf?"all1":"auto")<<" calls="<<calls
             <<" sec="<<elapsed<<" capped="<<(stop?1:0)<<"\n";
}
