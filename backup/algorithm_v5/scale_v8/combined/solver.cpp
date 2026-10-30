#include <bits/stdc++.h>
#include "event_scheduler.hpp"
#include "grouped_placement.hpp"
#include "list_scheduler.hpp"
#include "local_engine_polish.hpp"
using namespace std;
using i128 = __int128_t;

istream& operator>>(istream& in, i128& v) {
    string s; if (!(in >> s)) return in;
    v = 0; for (char c : s) if (c >= '0' && c <= '9') v = v*10 + c-'0';
    return in;
}
i128 cd(i128 a, i128 b) { return (a+b-1)/b; }
string dec(i128 x) { if (!x) return "0"; string s; while (x) { s += char('0'+x%10); x/=10; } reverse(s.begin(),s.end()); return s; }

struct In {
    int N,S,L,E,k,mb;
    i128 M,Bi,Bo,Z,Zs,U,Ua,d,b,Fs,Fio,Fin,ax,bx;
    vector<i128> T;
    vector<vector<i128>> load;
};
In read_input() {
    In x;
    cin>>x.N>>x.S>>x.M>>x.Bi>>x.Bo;
    cin>>x.L>>x.E>>x.Z>>x.Zs>>x.U>>x.Ua>>x.k>>x.mb>>x.Fs>>x.Fio>>x.Fin>>x.ax>>x.bx;
    cin>>x.d>>x.b;
    x.T.resize(x.L); x.load.resize(x.L);
    for(int l=0;l<x.L;l++) {
        cin>>x.T[l]; x.load[l].resize(x.E); string line; getline(cin,line);
        stringstream ss(line); vector<i128> a; i128 z; while(ss>>z) a.push_back(z);
        if((int)a.size()==x.E) x.load[l]=a;
        else { i128 base=x.T[l]/x.E,rem=x.T[l]%x.E; for(int e=0;e<x.E;e++)x.load[l][e]=base+(e<rem); }
    }
    return x;
}
struct Cand { int P=0,V=0; i128 score=0; vector<int> cuts; vector<vector<int>> map; };
struct PCand { Cand bestV,maxV; i128 probeTime=((i128)1<<126); };
struct Result { Cand c; int G=0,K=0; i128 time=((i128)1<<126); vector<int> cuts,group; vector<event_sched::Op> ops; };

vector<vector<int>> make_map(const In& x,int P,i128& cost) {
    vector<vector<int>> mp(x.L,vector<int>(x.E)); cost=0;
    for(int l=0;l<x.L;l++) {
        vector<int> e(x.E); iota(e.begin(),e.end(),0);
        sort(e.begin(),e.end(),[&](int a,int b){return x.load[l][a]>x.load[l][b];});
        vector<i128> loads(P); vector<int> cnt(P);
        for(int id:e) { int r=-1; for(int j=0;j<P;j++) if(cnt[j]<x.E/P&&(r<0||loads[j]<loads[r]))r=j; mp[l][id]=r; ++cnt[r]; loads[r]+=x.load[l][id]; }
        i128 total=0,heavy=0,sq=0; for(auto v:x.load[l]){total+=v;heavy=max(heavy,v);} for(auto v:loads)sq+=v*v;
        for(int it=0;it<6;it++) {
            i128 mx=*max_element(loads.begin(),loads.end()); if(mx==max(heavy,cd(total,P)))break;
            vector<int> order(P);iota(order.begin(),order.end(),0);sort(order.begin(),order.end(),[&](int a,int b){return loads[a]>loads[b];});
            int be=-1,bf=-1;i128 bm=mx,bs=sq;
            for(int a=0;a<x.E;a++)for(int b=a+1;b<x.E;b++) {
                int ra=mp[l][a],rb=mp[l][b];if(ra==rb)continue;
                i128 na=loads[ra]-x.load[l][a]+x.load[l][b],nb=loads[rb]-x.load[l][b]+x.load[l][a],outside=0;
                for(int r:order)if(r!=ra&&r!=rb){outside=loads[r];break;}
                i128 nm=max(outside,max(na,nb)),ns=sq-loads[ra]*loads[ra]-loads[rb]*loads[rb]+na*na+nb*nb;
                if(nm<bm||(nm==bm&&ns<bs)){bm=nm;bs=ns;be=a;bf=b;}
            }
            if(be<0)break;int ra=mp[l][be],rb=mp[l][bf];loads[ra]=loads[ra]-x.load[l][be]+x.load[l][bf];loads[rb]=loads[rb]-x.load[l][bf]+x.load[l][be];swap(mp[l][be],mp[l][bf]);sq=bs;
        }
        cost+=*max_element(loads.begin(),loads.end());
    }
    return mp;
}
vector<array<i128,10>> durations(const In& x,const Cand& c) {
    vector<array<i128,10>> d(x.L);i128 H=x.d*x.b/x.k;
    for(int l=0;l<x.L;l++) {
        vector<i128> load(c.P);for(int e=0;e<x.E;e++)load[c.map[l][e]]+=x.load[l][e];
        i128 m=*max_element(load.begin(),load.end()),X=cd(x.T[l]*H,c.P),pin=min(c.P,x.S)-1,pout=c.P-1-pin;
        i128 com=max(cd(pin*X,x.Bi),cd(pout*X,x.Bo))*x.Fio,g=m*x.Fin,s=x.T[l]*x.Fs;
        d[l]={s,com,g,com,cd(x.ax*s,1000000),cd(x.ax*com,1000000),cd(x.ax*g,1000000),cd(x.ax*x.bx*g,1000000000000LL),cd(x.ax*com,1000000),cd(x.ax*x.bx*s,1000000000000LL)};
    }
    return d;
}
Result evaluate(const In& x,const Cand& c,bool rich,bool deep,chrono::steady_clock::time_point deadline=chrono::steady_clock::time_point::max()) {
    Result best;best.c=c;auto dur=durations(x,c);vector<int> baseGroup(x.L);
    for(int g=0;g<c.V;g++)for(int l=c.cuts[g];l<c.cuts[g+1];l++)baseGroup[l]=g;
    auto test_layout=[&](const vector<int>& lg,const vector<int>& cuts,int K,int G) {
        if(chrono::steady_clock::now()>=deadline)return;
        vector<int> ng(G);for(int g:lg)ng[g]++;
        vector<int> windows=rich?vector<int>{1,2,G,2*G,0}:vector<int>{0};
        sort(windows.begin(),windows.end());windows.erase(unique(windows.begin(),windows.end()),windows.end());
        for(int one=0;one<=(rich?1:0);one++) {
            vector<int> caps(G),buf(G);bool ok=true;
            for(int g=0;g<G;g++) {
                bool zero=true;for(int l=0;l<x.L;l++)if(lg[l]==g&&(dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8]))zero=false;
                int bbuf=zero?0:1;
                if(rich&&!one&&!zero){i128 two=x.M-ng[g]*((x.E/c.P)*x.Z+x.Zs)-2*x.U;if(two>=0&&two/x.Ua>=ng[g])bbuf=2;}
                i128 avail=x.M-ng[g]*((x.E/c.P)*x.Z+x.Zs)-(zero?0:bbuf*x.U);if(avail<0){ok=false;break;}
                caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);buf[g]=bbuf;if(caps[g]<ng[g]){ok=false;break;}
            }
            if(!ok)continue;
            int mmax=rich?2:0;
            for(int mode=0;mode<=mmax;mode++)for(int w:windows) {
                if(chrono::steady_clock::now()>=deadline)return;
                vector<event_sched::Op> ops;i128 tm;
                if(event_sched::schedule(x.mb,x.L,G,lg,dur,ng,caps,buf,w,ops,tm,mode)&&tm<best.time) {
                    best.time=tm;best.G=G;best.K=K;best.cuts=cuts;best.group=lg;best.ops.swap(ops);
                }
            }
        }
    };
    test_layout(baseGroup,c.cuts,c.V,c.V);
    if(rich&&deep) {
        int maxG=min(x.L/2,x.N*x.S/c.P);set<int> gs;
        for(int g:{maxG,min(maxG,c.V),max(1,min(maxG,c.V/2))})if(g>=1&&g<=maxG)gs.insert(g);
        for(int G:gs){if(chrono::steady_clock::now()>=deadline)break;int K=2*G;vector<int> cuts(K+1),group(x.L);for(int j=0;j<=K;j++)cuts[j]=x.L*j/K;for(int j=0;j<K;j++)for(int l=cuts[j];l<cuts[j+1];l++)group[l]=(j<G?j:2*G-1-j);test_layout(group,cuts,K,G);}
        if(best.time<((i128)1<<126)) {
            vector<i128> lw(x.L);for(int l=0;l<x.L;l++)for(auto v:dur[l])lw[l]+=v;
            vector<int> order;for(int j=1;j<best.K;j++)if(best.cuts[j]>0&&best.cuts[j]<x.L)order.push_back(j);
            sort(order.begin(),order.end(),[&](int a,int b){return abs((long long)(lw[best.cuts[a]-1]-lw[best.cuts[a]]))>abs((long long)(lw[best.cuts[b]-1]-lw[best.cuts[b]]));});
            vector<int> seed=best.cuts;int K=best.K,G=best.G;int tried=0;
            for(int j:order){if(chrono::steady_clock::now()>=deadline)break;for(int delta:{-1,1}){if(chrono::steady_clock::now()>=deadline)break;auto cuts=seed;cuts[j]+=delta;bool ok=true;for(int z=1;z<K;z++)if(cuts[z]<=cuts[z-1]||cuts[z]>=cuts[z+1])ok=false;if(!ok)continue;vector<int> group(x.L);for(int bl=0;bl<K;bl++){int g=(K==G?bl:(bl<G?bl:2*G-1-bl));for(int l=cuts[bl];l<cuts[bl+1];l++)group[l]=g;}test_layout(group,cuts,K,G);}if(++tried>=3)break;}
        }
    }
    if(best.time>=((i128)1<<126)) {
        best.G=c.V;best.K=c.V;best.cuts=c.cuts;best.group=baseGroup;best.time=0;
        for(int mb=0;mb<x.mb;mb++)for(int l=0;l<x.L;l++)for(auto d:dur[l])best.time+=d+1;
    }
    return best;
}

Result scan_release1(const In& x,const Result& anchor,
                    chrono::steady_clock::time_point deadline,bool& cutoff) {
    Result trial=anchor;
    auto dur=durations(x,anchor.c);
    vector<int> ng(anchor.G);
    for(int g:anchor.group) ++ng[g];
    vector<int> wins;
    if(x.mb<=64) {
        for(int w=1;w<=x.mb;++w) wins.push_back(w);
    } else {
        wins={1,2,30,31,32,64,anchor.G,max(1,anchor.G-1),
              anchor.G+1,2*anchor.G,max(1,2*anchor.G-1),2*anchor.G+1,x.mb};
        for(int& w:wins) w=min(w,x.mb);
        sort(wins.begin(),wins.end());
        wins.erase(unique(wins.begin(),wins.end()),wins.end());
    }
    for(int one=0;one<=1 && !cutoff;++one) {
        vector<int> caps(anchor.G),buf(anchor.G);
        bool ok=true;
        for(int g=0;g<anchor.G;++g) {
            bool zero=true;
            for(int l=0;l<x.L;++l) if(anchor.group[l]==g &&
                (dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8])) zero=false;
            int b=zero?0:1;
            if(!zero && !one) {
                i128 two=x.M-(i128)ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs)-2*x.U;
                if(two>=0 && two/x.Ua>=ng[g]) b=2;
            }
            i128 avail=x.M-(i128)ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs)-(zero?0:b*x.U);
            if(avail<0) {ok=false;break;}
            caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);
            buf[g]=b;
            if(caps[g]<ng[g]) {ok=false;break;}
        }
        if(!ok) continue;
        for(int w:wins) {
            if(chrono::steady_clock::now()>=deadline) {cutoff=true;break;}
            vector<event_sched::Op> ops;
            i128 tm;
            if(event_sched::schedule(x.mb,x.L,anchor.G,anchor.group,dur,ng,
                                     caps,buf,w,ops,tm,0,0,0,0,false,1) &&
               tm<trial.time) {
                trial.time=tm;
                trial.ops.swap(ops);
            }
        }
    }
    return trial;
}

int main(int argc,char**argv) {
    auto mainStart=chrono::steady_clock::now();ios::sync_with_stdio(false);cin.tie(nullptr);In x=read_input();int R=x.N*x.S; i128 H=x.d*x.b/x.k;
    int forceP=0;bool serial=false,doList=false,listDeep=false,listDeepTopos=false,forceWave=false;string borrow="ac",diff="auto",scale="auto";for(int i=1;i<argc;i++){string a=argv[i];if(a=="--baseline")serial=true;else if(a=="--list")doList=true;else if(a=="--list-deep"){doList=true;listDeep=true;}else if(a=="--list-deep-topos"){doList=true;listDeep=true;listDeepTopos=true;}else if(a=="--wave")forceWave=true;else if(a.rfind("--scale=",0)==0)scale=a.substr(8);else if(a.rfind("--force-p=",0)==0)forceP=stoi(a.substr(10));else if(a.rfind("--borrow=",0)==0)borrow=a.substr(9);else if(a.rfind("--diff=",0)==0)diff=a.substr(7);}
    bool diffEnabled=!serial&&(diff=="on"||(diff=="auto"&&borrow=="ac"));
    if(diffEnabled) doList=true;
    if(diff=="off") doList=false;
    bool doWave=!serial&&(forceWave||scale=="on"||(scale=="auto"&&borrow=="ac"&&diff=="auto"));
    if(borrow=="none"||diff=="off"||scale=="off")doWave=false;
    vector<PCand> pcs;
    for(int P=1;P<=min(R,x.E);P++) {
        if((forceP&&P!=forceP)||x.E%P||(x.S%P&&P%x.S))continue;
        i128 mapcost;auto mp=make_map(x,P,mapcost);i128 q=(x.E/P)*x.Z+x.Zs;
        bool zeroComms=true;vector<i128> pref(x.L+1);
        for(int l=0;l<x.L;l++){i128 X=cd(x.T[l]*H,P),pin=min(P,x.S)-1,pout=P-1-pin; i128 com=max(cd(pin*X,x.Bi),cd(pout*X,x.Bo))*x.Fio,g=cd(x.T[l],P)*x.Fin,s=x.T[l]*x.Fs;if(com)zeroComms=false;pref[l+1]=pref[l]+4*com+2*g+2*s+2*cd(x.ax*com,1000000)+cd(x.ax*g,1000000)+cd(x.ax*x.bx*g,1000000000000LL)+cd(x.ax*s,1000000)+cd(x.ax*x.bx*s,1000000000000LL);}
        PCand pc; i128 bestScore=((i128)1<<126);int vmax=min({x.L,64,R/P});
        for(int V=1;V<=vmax;V++) {
            i128 INF=((i128)1<<126);vector<vector<i128>> dp(V+1,vector<i128>(x.L+1,INF));vector<vector<int>> par(V+1,vector<int>(x.L+1,-1));dp[0][0]=0;
            for(int j=1;j<=V;j++)for(int i=j;i<=x.L-(V-j);i++)for(int h=j-1;h<i;h++)if(dp[j-1][h]<INF&&(i-h)*(q+x.Ua)+(zeroComms?0:x.U)<=x.M){i128 val=max(dp[j-1][h],pref[i]-pref[h]);if(val<dp[j][i])dp[j][i]=val,par[j][i]=h;}
            if(dp[V][x.L]>=INF)continue;Cand c;c.P=P;c.V=V;c.score=dp[V][x.L]*1000000+mapcost;c.map=mp;c.cuts.resize(V+1);c.cuts[V]=x.L;int at=x.L;bool ok=true;
            for(int j=V;j>0;j--){int h=par[j][at];if(h<0){ok=false;break;}c.cuts[j-1]=h;at=h;}if(!ok)continue;
            if(c.score<bestScore){bestScore=c.score;pc.bestV=c;}pc.maxV=c;
        }
        if(pc.maxV.P)pcs.push_back(move(pc));
    }
    if(pcs.empty()){cerr<<"no feasible config\n";return 2;}
    vector<Result> probes;probes.reserve(pcs.size());
    for(auto& pc:pcs){Result r=evaluate(x,pc.maxV,false,false);pc.probeTime=r.time;probes.push_back(move(r));}
    int winner=0;for(int i=1;i<(int)probes.size();i++)if(probes[i].time<probes[winner].time)winner=i;
    Result best=move(probes[winner]);
    Result probe_base=best;
    if(!serial) {
        vector<int> ord(pcs.size());iota(ord.begin(),ord.end(),0);sort(ord.begin(),ord.end(),[&](int a,int b){return pcs[a].probeTime<pcs[b].probeTime;});
        if(winner!=ord[0])swap(ord[0],ord[find(ord.begin(),ord.end(),winner)-ord.begin()]);
        for(int j=0;j<min(2,(int)ord.size());j++){int id=ord[j];const Cand& c=pcs[id].bestV.P?pcs[id].bestV:pcs[id].maxV;Result r=evaluate(x,c,true,j==0);if(r.time<best.time)best=move(r);}
    }
    // Freeze the complete v5 result, including its original P/V and rich schedule
    // competition. Every borrow experiment branches from this exact incumbent.
    Result v5_base=best;
    if(!serial&&(borrow=="windows"||borrow=="ac"||borrow=="all")) {
        auto scan_windows=[&](const Result& anchor){Result trial=anchor;auto dur=durations(x,anchor.c);vector<int> ng(anchor.G);for(int g:anchor.group)ng[g]++;
            vector<int> wins;if(x.mb<=64){for(int w=1;w<=x.mb;w++)wins.push_back(w);}else wins={1,2,30,31,32,64,0,anchor.G,2*anchor.G,max(1,anchor.G-1),anchor.G+1,max(1,2*anchor.G-1),2*anchor.G+1};
            sort(wins.begin(),wins.end());wins.erase(unique(wins.begin(),wins.end()),wins.end());
            for(int one=0;one<=1;one++){vector<int> caps(anchor.G),buf(anchor.G);bool ok=true;for(int g=0;g<anchor.G;g++){bool zero=true;for(int l=0;l<x.L;l++)if(anchor.group[l]==g&&(dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8]))zero=false;int b=zero?0:1;if(!zero&&!one){i128 two=x.M-ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs)-2*x.U;if(two>=0&&two/x.Ua>=ng[g])b=2;}i128 avail=x.M-ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs)-(zero?0:b*x.U);if(avail<0){ok=false;break;}caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);buf[g]=b;if(caps[g]<ng[g]){ok=false;break;}}
                if(ok)for(int w:wins){vector<event_sched::Op> ops;i128 tm;if(event_sched::schedule(x.mb,x.L,anchor.G,anchor.group,dur,ng,caps,buf,w,ops,tm,0)&&tm<trial.time){trial.time=tm;trial.ops.swap(ops);}}
            }return trial;};
        Result a=scan_windows(probe_base),b=scan_windows(v5_base);Result trial=(a.time<=b.time?move(a):move(b));if(trial.time<best.time)best=move(trial);
    }
    if(!serial&&(borrow=="boost"||borrow=="boost_grid"||borrow=="all")) {
        Result trial=v5_base;auto dur=durations(x,v5_base.c);vector<int> ng(v5_base.G);for(int g:v5_base.group)ng[g]++;
        i128 boostBestTime=((i128)1<<126);int bestFg=0,bestFm=0,bestRatio=0,bestBuffer=0;bool bestFlat=false;
        for(int one=0;one<=1;one++){vector<int> caps(v5_base.G),buf(v5_base.G);bool ok=true;for(int g=0;g<v5_base.G;g++){bool zero=true;for(int l=0;l<x.L;l++)if(v5_base.group[l]==g&&(dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8]))zero=false;int b=zero?0:1;if(!zero&&!one){i128 two=x.M-ng[g]*((x.E/v5_base.c.P)*x.Z+x.Zs)-2*x.U;if(two>=0&&two/x.Ua>=ng[g])b=2;}i128 avail=x.M-ng[g]*((x.E/v5_base.c.P)*x.Z+x.Zs)-(zero?0:b*x.U);if(avail<0){ok=false;break;}caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);buf[g]=b;if(caps[g]<ng[g]){ok=false;break;}}
            if(!ok)continue;vector<tuple<int,int,int,bool,bool>> cfg;
            if(borrow=="boost_grid") {set<int> fss={1,2,max(1,v5_base.G/2),v5_base.G},fms={max(1,x.mb/4),max(1,x.mb/2),x.mb};vector<int> ratios={0,5,10,20,50,100};for(int fg:fss)for(int fm0:fms)for(int ratio:ratios)cfg.emplace_back(fg,fm0,ratio,false,false);cfg.emplace_back(min(2,v5_base.G),min(x.mb,max(1,x.mb/2)),20,true,false);}
            else {int fs=min(v5_base.G,max(1,v5_base.G/2)),fm=min(x.mb,16);cfg.emplace_back(v5_base.G,min(x.mb,max(2,v5_base.G)),0,false,false);cfg.emplace_back(fs,fm,10,false,false);cfg.emplace_back(fs,fm,20,false,false);cfg.emplace_back(fs,fm,50,false,false);cfg.emplace_back(min(2,v5_base.G),min(x.mb,8),20,true,false);}
            for(auto [fg,fm0,ratio,flat,unused]:cfg){(void)unused;vector<event_sched::Op> ops;i128 tm;if(event_sched::schedule(x.mb,x.L,v5_base.G,v5_base.group,dur,ng,caps,buf,0,ops,tm,3,fg,fm0,ratio,flat)){if(tm<boostBestTime){boostBestTime=tm;bestFg=fg;bestFm=fm0;bestRatio=ratio;bestFlat=flat;bestBuffer=one;}if(tm<trial.time){trial.time=tm;trial.ops.swap(ops);}}}
        }
        if(borrow=="boost_grid"&&boostBestTime<((i128)1<<126))cerr<<"BORROW_B_GRID_BEST P="<<v5_base.c.P<<" G="<<bestFg<<" M="<<bestFm<<" ratio="<<bestRatio<<" flat="<<bestFlat<<" buffer="<<bestBuffer<<" Time="<<dec(boostBestTime)<<" base="<<dec(v5_base.time)<<"\n";
        if(trial.time<best.time)best=move(trial);
    }
    if(!serial&&(borrow=="placement"||borrow=="ac"||borrow=="all")) {
        Cand alt=v5_base.c;const int P=alt.P,per=x.E/P;bool changed=false;int improvedLayers=0;
        map<vector<i128>,grouped_placement::Plan> cache;
        for(int l=0;l<x.L;l++) {
            vector<i128> slots=x.load[l],key=slots;sort(key.begin(),key.end());
            vector<i128> baseLoad(P);for(int e=0;e<x.E;e++)baseLoad[alt.map[l][e]]+=slots[e];
            i128 cur=*max_element(baseLoad.begin(),baseLoad.end()),total=accumulate(slots.begin(),slots.end(),(i128)0),heavy=*max_element(slots.begin(),slots.end());
            i128 lower=max(cd(total,P),heavy);if(cur<=lower)continue;
            grouped_placement::Plan plan;bool found=false;auto it=cache.find(key);
            if(it!=cache.end()){plan=it->second;found=true;}
            else {
                i128 lo=lower,hi=cur-1;grouped_placement::Plan bestPlan;
                for(int z=0;z<12&&lo<=hi;z++){i128 mid=lo+(hi-lo)/2;grouped_placement::Plan trial;if(grouped_placement::find_at_peak(slots,P,per,mid,trial,250000)){bestPlan=move(trial);hi=mid-1;}else lo=mid+1;}
                if(bestPlan.peak){plan=move(bestPlan);cache.emplace(key,plan);found=true;}
            }
            if(!found)continue;vector<int> row;if(!grouped_placement::materialize(slots,plan,row))continue;
            vector<i128> newLoad(P);for(int e=0;e<x.E;e++)newLoad[row[e]]+=slots[e];i128 nm=*max_element(newLoad.begin(),newLoad.end());
            if(nm<cur){alt.map[l]=move(row);changed=true;++improvedLayers;}
        }
        if(changed) {
            Result trial=v5_base;trial.c=alt;auto dur=durations(x,alt);vector<int> ng(trial.G);for(int g:trial.group)ng[g]++;
            for(int one=0;one<=1;one++){vector<int> caps(trial.G),buf(trial.G);bool ok=true;for(int g=0;g<trial.G;g++){bool zero=true;for(int l=0;l<x.L;l++)if(trial.group[l]==g&&(dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8]))zero=false;int b=zero?0:1;if(!zero&&!one){i128 two=x.M-ng[g]*((x.E/P)*x.Z+x.Zs)-2*x.U;if(two>=0&&two/x.Ua>=ng[g])b=2;}i128 avail=x.M-ng[g]*((x.E/P)*x.Z+x.Zs)-(zero?0:b*x.U);if(avail<0){ok=false;break;}caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);buf[g]=b;if(caps[g]<ng[g]){ok=false;break;}}
                if(!ok)continue;vector<event_sched::Op> ops;i128 tm;if(event_sched::schedule(x.mb,x.L,trial.G,trial.group,dur,ng,caps,buf,0,ops,tm,0)&&tm<trial.time){trial.time=tm;trial.ops.swap(ops);}
            }
            if(borrow=="all"||borrow=="ac") {
                vector<int> wins;if(x.mb<=64){for(int w=1;w<=x.mb;w++)wins.push_back(w);}else wins={1,2,30,31,32,64,0,trial.G,2*trial.G,max(1,trial.G-1),trial.G+1};
                sort(wins.begin(),wins.end());wins.erase(unique(wins.begin(),wins.end()),wins.end());
                for(int one=0;one<=1;one++){vector<int> caps(trial.G),buf(trial.G);bool ok=true;for(int g=0;g<trial.G;g++){bool zero=true;for(int l=0;l<x.L;l++)if(trial.group[l]==g&&(dur[l][1]||dur[l][3]||dur[l][5]||dur[l][8]))zero=false;int b=zero?0:1;if(!zero&&!one){i128 two=x.M-ng[g]*((x.E/P)*x.Z+x.Zs)-2*x.U;if(two>=0&&two/x.Ua>=ng[g])b=2;}i128 avail=x.M-ng[g]*((x.E/P)*x.Z+x.Zs)-(zero?0:b*x.U);if(avail<0){ok=false;break;}caps[g]=(int)min<i128>(avail/x.Ua,(i128)x.mb*ng[g]);buf[g]=b;if(caps[g]<ng[g]){ok=false;break;}}
                    if(!ok)continue;for(int w:wins){vector<event_sched::Op> ops;i128 tm;if(event_sched::schedule(x.mb,x.L,trial.G,trial.group,dur,ng,caps,buf,w,ops,tm,0)&&tm<trial.time){trial.time=tm;trial.ops.swap(ops);}}
                }
            }
            if(trial.time<best.time){best=move(trial);cerr<<"BORROW_C P="<<P<<" improved_MAP_layers="<<improvedLayers<<" Time="<<dec(best.time)<<"\n";}
        }
    }
    if(!serial && doList) {
        auto listStart=chrono::steady_clock::now(); bool listCutoff=false;const auto listBudget=listDeep?chrono::milliseconds(30000):chrono::milliseconds(8000);
        Result anchor=best; auto dur=durations(x,anchor.c); vector<int> ng(anchor.G); for(int g:anchor.group)ng[g]++;
        auto safe=[&](const vector<event_sched::Op>& ops,i128& tm)->bool {
            int stride=x.L*10,N=x.mb*stride; vector<i128> st(N,-1),en(N,-1); tm=0;
            for(auto&o:ops){int id=(o.mb*x.L+o.l)*10+o.op;st[id]=o.start;en[id]=o.start+dur[o.l][o.op];tm=max(tm,en[id]);}
            for(int i=0;i<N;i++)if(st[i]<0)return false;
            auto peak=[](vector<pair<i128,i128>>& a){sort(a.begin(),a.end());multiset<i128> ends;int best=0;for(size_t i=0;i<a.size();){size_t j=i;while(j<a.size()&&a[j].first==a[i].first)j++;while(!ends.empty()&&*ends.begin()<a[i].first)ends.erase(ends.begin());best=max(best,(int)ends.size()+(int)(j-i));for(size_t k=i;k<j;k++)ends.insert(a[k].second);i=j;}return best;};
            for(int g=0;g<anchor.G;g++){i128 mexp=(i128)ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs);vector<pair<i128,i128>> acts,comms;for(int l=0;l<x.L;l++)if(anchor.group[l]==g)for(int m=0;m<x.mb;m++){int b=(m*x.L+l)*10;acts.push_back({en[b+3],st[b+4]});for(int o:{1,3,5,8})if(dur[l][o]>0)comms.push_back({st[b+o],en[b+o]});}i128 used=mexp+x.U*peak(comms)+x.Ua*peak(acts);if(used>x.M)return false;}
            return true;
        };
        i128 baseTime=anchor.time,busy=0;for(int g=0;g<anchor.G;g++){i128 csum=0,msum=0;for(int l=0;l<x.L;l++)if(anchor.group[l]==g)for(int o=0;o<10;o++)(list_sched::comm(o)?msum:csum)+=dur[l][o];busy=max(busy,max(csum,msum));}
        int bestW=0,bestVariant=-1,bestGap=0;string bestMode="incumbent";bool bestBoost=false;long double bestBoostValue=0;int bestFs=0,bestFm=0,bestRatio=0;bool bestRamp=false;i128 plainTime=((i128)1<<126);int plainW=x.mb;bool gapImproved=false,skipSweep=false;
        auto run=[&](int W,int vi,bool early,int gap,int fs,int fm,int ratio10,bool ramp){if(chrono::steady_clock::now()-mainStart>listBudget){listCutoff=true;return;}vector<list_sched::Op> lo; i128 tm; if(!list_sched::schedule(x.mb,x.L,anchor.G,anchor.group,dur,ng,W,vi,early,gap,fs,fm,busy,ratio10,ramp,lo,tm))return;if(tm>=best.time&&(ratio10>0||tm>=plainTime))return;vector<event_sched::Op> ops;ops.reserve(lo.size());for(auto&o:lo)ops.push_back({o.start,o.mb,o.l,o.op});i128 checked;if(!safe(ops,checked))return;if(ratio10==0&&checked<plainTime){plainTime=checked;plainW=W;}if(checked>=best.time)return;sort(ops.begin(),ops.end(),[](auto&a,auto&b){return tie(a.start,a.mb,a.l,a.op)<tie(b.start,b.mb,b.l,b.op);});best.time=checked;best.ops=move(ops);bestW=W;bestVariant=vi;bestGap=gap;bestMode=early?"early":"prio";bestBoost=ratio10>0;bestBoostValue=(long double)busy*ratio10/10;bestFs=fs;bestFm=fm;bestRatio=ratio10;bestRamp=ramp;};
        i128 nodeCount=(i128)x.mb*x.L*10;if(nodeCount>=5000&&nodeCount<=150000&&chrono::steady_clock::now()-mainStart<chrono::seconds(4)){vector<list_sched::Op> lo;i128 tm;if(list_sched::schedule(x.mb,x.L,anchor.G,anchor.group,dur,ng,x.mb,0,false,0,0,0,0,0,false,lo,tm,nullptr,nullptr,true,true)&&tm<best.time){vector<event_sched::Op> ops;ops.reserve(lo.size());for(auto&o:lo)ops.push_back({o.start,o.mb,o.l,o.op});i128 checked;if(safe(ops,checked)&&checked<best.time){sort(ops.begin(),ops.end(),[](auto&a,auto&b){return tie(a.start,a.mb,a.l,a.op)<tie(b.start,b.mb,b.l,b.op);});best.time=checked;best.ops=move(ops);bestW=x.mb;bestVariant=0;bestGap=0;bestMode="gap-fill";bestBoost=false;gapImproved=true;}}}
        if(diffEnabled&&borrow=="ac") {
            bool releaseCutoff=false;
            Result released=scan_release1(x,best,mainStart+chrono::seconds(8),releaseCutoff);
            if(released.time<best.time) best=move(released);
            listCutoff=listCutoff||releaseCutoff;
        }
        set<int> allW;if(x.mb<=64)for(int w=1;w<=x.mb;w++)allW.insert(w);else{for(int num:{1,2}){int w=x.mb*num/2;if(w>0)allW.insert(w);}for(auto [num,den]:vector<pair<int,int>>{{2,3},{1,1},{1,2},{1,3},{1,4},{1,5},{1,6},{1,8},{1,12},{1,16},{1,24},{1,32}}){int w=x.mb*num/den;if(w>0)allW.insert(w);}for(int w:{32,24,16,12,8,6,4,3,2,1})if(w<=x.mb)allW.insert(w);}
        i128 perLayer=(x.E/anchor.c.P)*x.Z+x.Zs;if(x.Ua>0)for(int g=0;g<anchor.G;g++){i128 mexp=(i128)ng[g]*perLayer,allowed=(x.M-mexp-x.U)/x.Ua;if(allowed>0&&ng[g]>0)allW.insert(max(1,min(x.mb,(int)(allowed/ng[g]))));}
        skipSweep=gapImproved&&(i128)best.time*100<=busy*x.mb*108;
        vector<int> preferred;auto addW=[&](int w){if(w>=1&&w<=x.mb&&allW.count(w)&&find(preferred.begin(),preferred.end(),w)==preferred.end())preferred.push_back(w);};
        for(int w:{x.mb,anchor.G,2*anchor.G,anchor.G-1,anchor.G+1,2*anchor.G-1,2*anchor.G+1})addW(w);
        for(auto [num,den]:vector<pair<int,int>>{{1,1},{2,3},{1,2},{1,3},{1,4},{1,5},{1,6},{1,8},{1,12},{1,16},{1,24},{1,32}})addW(x.mb*num/den);
        for(int w:{32,24,16,12,8,6,4,3,2,1})addW(w);
        for(int w:allW)addW(w);vector<int> wins=preferred;
        const int priorityVariants[]={4,5,0};if(!skipSweep)for(int vi:priorityVariants)for(int w:wins)for(int gap:{0,1})run(w,vi,true,gap,0,0,0,false);
        // Try the most useful alternative topologies and priority mode after every window has had its early pass.
        if(!skipSweep&&(!listDeep||listDeepTopos))for(int vi:{1,2,3,6,7})for(int w:wins)run(w,vi,true,0,0,0,0,false);
        if(!skipSweep&&(!listDeep||listDeepTopos))for(int vi=0;vi<8;vi++)for(int w:wins)run(w,vi,false,0,0,0,0,false);
        int chosenW=plainTime<((i128)1<<126)?plainW:x.mb; // best safe unboosted list schedule
        set<int> fss,fms={x.mb,max(1,x.mb/2),max(1,x.mb/4)};for(int fs:{1,2,max(1,x.mb/4),max(1,x.mb/2),anchor.G})fss.insert(min(fs,anchor.G));vector<int> ratios={5,10,20,50,100};
        if(!skipSweep&&!listDeepTopos&&(x.mb<=64 || (long double)x.mb<=1.2L*anchor.G || (long double)baseTime/max((long double)1,(long double)busy*x.mb)>1.25L)){vector<int> boostWs;if(listDeep){for(int w:preferred)if(find(boostWs.begin(),boostWs.end(),w)==boostWs.end())boostWs.push_back(w);}else boostWs.push_back(chosenW);for(int w:boostWs)for(int vi:{4,5})for(int fs:fss)for(int fm:fms)for(int r:ratios)run(w,vi,true,0,min(fs,anchor.G),min(fm,x.mb),r,true);if(!listDeep){for(int vi:{4,5})for(int fs:fss)for(int fm:fms)for(int r:ratios)run(chosenW,vi,true,0,min(fs,anchor.G),min(fm,x.mb),r,false);for(int vi:{0,1,2,3,6,7})for(int fs:fss)for(int fm:fms)for(int r:ratios)for(bool ramp:{true,false})run(chosenW,vi,true,0,min(fs,anchor.G),min(fm,x.mb),r,ramp);}}
        cerr<<"LIST_V7 anchor="<<dec(baseTime)<<" plain="<<(plainTime<((i128)1<<126)?dec(plainTime):"none")<<" plainW="<<plainW<<" best="<<dec(best.time)<<" W="<<bestW<<" mode="<<bestMode<<" variant="<<bestVariant<<" gap="<<bestGap<<" boost="<<bestBoostValue<<" fs="<<bestFs<<" fm="<<bestFm<<" ratio10="<<bestRatio<<" ramp="<<bestRamp<<" cutoff="<<listCutoff<<" main_seconds="<<chrono::duration<double>(chrono::steady_clock::now()-mainStart).count()<<" checked=closed-interval\n";
    }
    Result v7Incumbent=best;vector<Result> scaleAltSeeds;
    if(!serial&&doWave&&x.mb<=16&&(i128)x.mb*x.L*10<=8000&&x.L>best.G&&chrono::steady_clock::now()-mainStart<chrono::seconds(8)){
        const int incumbentP=best.c.P;vector<int> order(pcs.size());iota(order.begin(),order.end(),0);sort(order.begin(),order.end(),[&](int a,int b){return pcs[a].probeTime<pcs[b].probeTime;});int used=0;auto altDeadline=mainStart+chrono::seconds(9);
        for(int pi:order){const Cand& c=pcs[pi].bestV.P?pcs[pi].bestV:pcs[pi].maxV;if(!c.P||c.P==incumbentP)continue;if(used>=2||chrono::steady_clock::now()+chrono::seconds(1)>=altDeadline)break;auto dAlt=durations(x,c);int maxV=max(1,min({x.L,64,x.N*x.S/c.P}));i128 maxC=0,maxN=0,totalC=0,totalN=0;for(int l=0;l<x.L;l++){i128 C=0,N=0;for(int o=0;o<10;o++)(list_sched::comm(o)?N:C)+=dAlt[l][o];maxC=max(maxC,C);maxN=max(maxN,N);totalC+=C;totalN+=N;}i128 lb=max({(i128)x.mb*maxC,(i128)x.mb*maxN,cd((i128)x.mb*totalC,maxV),cd((i128)x.mb*totalN,maxV)});if(lb>=best.time)continue;++used;Result alt=evaluate(x,c,true,true,altDeadline);if(alt.ops.empty())continue;scaleAltSeeds.push_back(alt);if(alt.time<best.time){cerr<<"SCALE_ALT_P oldP="<<best.c.P<<" newP="<<alt.c.P<<" old="<<dec(best.time)<<" new="<<dec(alt.time)<<" LB="<<dec(lb)<<"\n";best=alt;}}
    }
    if(!serial&&doWave){
      vector<Result> scaleSeeds;scaleSeeds.push_back(v7Incumbent);for(auto&alt:scaleAltSeeds)scaleSeeds.push_back(alt);
      for(Result anchor:scaleSeeds){if(chrono::steady_clock::now()-mainStart>=chrono::seconds(9))break;Result savedBest=best;best=anchor;
        const auto waveStart=chrono::steady_clock::now();auto dur=durations(x,anchor.c);vector<int> ng(anchor.G);for(int g:anchor.group)ng[g]++;
        auto safeWave=[&](const vector<event_sched::Op>&ops,i128&tm){int stride=x.L*10,N=x.mb*stride;vector<i128> st(N,-1),en(N,-1);tm=0;for(auto&o:ops){int id=(o.mb*x.L+o.l)*10+o.op;st[id]=o.start;en[id]=o.start+dur[o.l][o.op];tm=max(tm,en[id]);}for(int i=0;i<N;i++)if(st[i]<0)return false;auto peak=[](vector<pair<i128,i128>>&a){sort(a.begin(),a.end());multiset<i128> ends;int best=0;for(size_t i=0;i<a.size();){size_t j=i;while(j<a.size()&&a[j].first==a[i].first)j++;while(!ends.empty()&&*ends.begin()<a[i].first)ends.erase(ends.begin());best=max(best,(int)ends.size()+(int)(j-i));for(size_t k=i;k<j;k++)ends.insert(a[k].second);i=j;}return best;};for(int g=0;g<anchor.G;g++){i128 mexp=(i128)ng[g]*((x.E/anchor.c.P)*x.Z+x.Zs);vector<pair<i128,i128>> acts,comms;for(int l=0;l<x.L;l++)if(anchor.group[l]==g)for(int m=0;m<x.mb;m++){int b=(m*x.L+l)*10;acts.push_back({en[b+3],st[b+4]});for(int o:{1,3,5,8})if(dur[l][o]>0)comms.push_back({st[b+o],en[b+o]});}if(mexp+x.U*peak(comms)+x.Ua*peak(acts)>x.M)return false;}return true;};
        struct Trial{i128 tm;int mode,A,B,phase,pn,pd,W,head,desc,dw;};vector<Trial> top;Trial winner{anchor.time,0,0,0,0,0,0,x.mb,0,0,0};
        auto runWave=[&](int mode,int A,int B,int phase,int pn,int pd,int head,bool desc,int dw,int W){if(chrono::steady_clock::now()-mainStart>chrono::milliseconds(9000))return;vector<list_sched::Op> lo;i128 tm;if(!list_sched::schedule(x.mb,x.L,anchor.G,anchor.group,dur,ng,W,0,false,0,0,0,0,0,false,lo,tm,nullptr,nullptr,false,true,mode,A,B,phase,pn,pd,head,desc,dw))return;vector<event_sched::Op> ops;ops.reserve(lo.size());for(auto&o:lo)ops.push_back({o.start,o.mb,o.l,o.op});i128 checked;if(!safeWave(ops,checked))return;if(W==x.mb){Trial t{checked,mode,A,B,phase,pn,pd,W,head,0,dw};top.push_back(t);sort(top.begin(),top.end(),[](auto&a,auto&b){return a.tm<b.tm;});if(top.size()>2)top.pop_back();}if(checked<best.time){winner={checked,mode,A,B,phase,pn,pd,W,head,0,dw};sort(ops.begin(),ops.end(),[](auto&a,auto&b){return tie(a.start,a.mb,a.l,a.op)<tie(b.start,b.mb,b.l,b.op);});best.time=checked;best.ops=move(ops);}};
        vector<int> pitches={1,2,4};runWave(1,2,1,0,1,1,0,false,0,x.mb);
        for(int pn:pitches)for(int head:{1,2})runWave(2,1,1,0,pn,4,head,false,0,x.mb);
        runWave(2,1,1,0,2,4,2,false,1,x.mb);runWave(2,1,1,0,2,4,2,false,2,x.mb);
        vector<int> ws={anchor.G,2*anchor.G,max(1,x.mb/2),x.mb};sort(ws.begin(),ws.end());ws.erase(unique(ws.begin(),ws.end()),ws.end());for(size_t i=0;i<top.size()&&i<2;i++)for(int w:ws)if(w!=x.mb){auto t=top[i];runWave(t.mode,t.A,t.B,t.phase,t.pn,t.pd,t.head,t.desc,t.dw,w);}
        cerr<<"WAVE_V8 anchor="<<dec(anchor.time)<<" best="<<dec(best.time)<<" improvement="<<dec(anchor.time-best.time)<<" mode="<<winner.mode<<" A="<<winner.A<<" B="<<winner.B<<" phase="<<winner.phase<<" pitch="<<winner.pn<<"/"<<winner.pd<<" head="<<(winner.head==1?"ES":winner.head==2?"EF":"layerMean")<<" dw="<<winner.dw<<" W="<<winner.W<<" top="<<top.size()<<" elapsed="<<chrono::duration<double>(chrono::steady_clock::now()-waveStart).count()<<" total="<<chrono::duration<double>(chrono::steady_clock::now()-mainStart).count()<<"\n";
        Result waveResult=best;best=move(savedBest);if(waveResult.time<best.time)best=move(waveResult);
      }
    }
    if(!serial&&doWave&&!best.ops.empty()&&(i128)x.mb*x.L*10<=8000&&chrono::steady_clock::now()+chrono::milliseconds(100)<mainStart+chrono::seconds(9)){
        auto dur=durations(x,best.c);local_engine_polish::Stats total;total.exhausted=true;i128 resident=(x.E/best.c.P)*x.Z+x.Zs;auto deadline=mainStart+chrono::seconds(9);
        for(int round=0;round<4&&chrono::steady_clock::now()+chrono::milliseconds(100)<deadline;round++){
            vector<event_sched::Op> polished;i128 polTime=best.time;local_engine_polish::Stats part;
            local_engine_polish::polish(x.mb,x.L,best.G,best.group,dur,best.ops,x.M,x.U,x.Ua,resident,polished,polTime,part,deadline,3000);
            total.evaluated+=part.evaluated;total.accepted+=part.accepted;total.strict_improve+=part.strict_improve;total.tie_moves+=part.tie_moves;total.rounds++;total.exhausted=total.exhausted&&part.exhausted;
            if(part.accepted==0)break;if(polTime<best.time)best.time=polTime;best.ops.swap(polished);
        }
        cerr<<"LOCAL_ENGINE evaluated="<<total.evaluated<<" accepted="<<total.accepted<<" strict_improve="<<total.strict_improve<<" tie_moves="<<total.tie_moves<<" rounds="<<total.rounds<<" Time="<<dec(best.time)<<" exhausted="<<total.exhausted<<" main_seconds="<<chrono::duration<double>(chrono::steady_clock::now()-mainStart).count()<<"\n";
    }
    const array<string,10> names={"s","disp","gemm","comb","s_bwd","comb_bwd","gemm_dx","gemm_dw","disp_bwd","s_dw"};
    cout<<best.G<<" "<<best.c.P<<"\nPSI\n"<<best.K;for(int j=1;j<best.K;j++)cout<<" "<<best.cuts[j];cout<<"\nMAP\n";
    for(auto&r:best.c.map){for(int e=0;e<x.E;e++)cout<<(e?" ":"")<<r[e];cout<<"\n";}cout<<"SCHEDULE\n";
    if(serial){auto dur=durations(x,best.c);i128 t=0;auto emit=[&](int mb,int l,int op){cout<<dec(t)<<" "<<mb<<":"<<l<<":"<<names[op]<<"\n";t+=dur[l][op]+1;};for(int mb=0;mb<x.mb;mb++){for(int l=0;l<x.L;l++){emit(mb,l,0);emit(mb,l,1);emit(mb,l,2);emit(mb,l,3);}for(int l=x.L-1;l>=0;l--){emit(mb,l,5);emit(mb,l,4);emit(mb,l,6);emit(mb,l,8);emit(mb,l,7);emit(mb,l,9);}}}
    else for(auto&o:best.ops)cout<<dec(o.start)<<" "<<o.mb<<":"<<o.l<<":"<<names[o.op]<<"\n";
}
