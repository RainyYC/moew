#include <bits/stdc++.h>
#include "event_scheduler.hpp"
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
Result evaluate(const In& x,const Cand& c,bool rich,bool deep) {
    Result best;best.c=c;auto dur=durations(x,c);vector<int> baseGroup(x.L);
    for(int g=0;g<c.V;g++)for(int l=c.cuts[g];l<c.cuts[g+1];l++)baseGroup[l]=g;
    auto test_layout=[&](const vector<int>& lg,const vector<int>& cuts,int K,int G) {
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
        for(int G:gs){int K=2*G;vector<int> cuts(K+1),group(x.L);for(int j=0;j<=K;j++)cuts[j]=x.L*j/K;for(int j=0;j<K;j++)for(int l=cuts[j];l<cuts[j+1];l++)group[l]=(j<G?j:2*G-1-j);test_layout(group,cuts,K,G);}
        if(best.time<((i128)1<<126)) {
            vector<i128> lw(x.L);for(int l=0;l<x.L;l++)for(auto v:dur[l])lw[l]+=v;
            vector<int> order;for(int j=1;j<best.K;j++)if(best.cuts[j]>0&&best.cuts[j]<x.L)order.push_back(j);
            sort(order.begin(),order.end(),[&](int a,int b){return abs((long long)(lw[best.cuts[a]-1]-lw[best.cuts[a]]))>abs((long long)(lw[best.cuts[b]-1]-lw[best.cuts[b]]));});
            vector<int> seed=best.cuts;int K=best.K,G=best.G;int tried=0;
            for(int j:order){for(int delta:{-1,1}){auto cuts=seed;cuts[j]+=delta;bool ok=true;for(int z=1;z<K;z++)if(cuts[z]<=cuts[z-1]||cuts[z]>=cuts[z+1])ok=false;if(!ok)continue;vector<int> group(x.L);for(int bl=0;bl<K;bl++){int g=(K==G?bl:(bl<G?bl:2*G-1-bl));for(int l=cuts[bl];l<cuts[bl+1];l++)group[l]=g;}test_layout(group,cuts,K,G);}if(++tried>=3)break;}
        }
    }
    if(best.time>=((i128)1<<126)) {
        best.G=c.V;best.K=c.V;best.cuts=c.cuts;best.group=baseGroup;best.time=0;
        for(int mb=0;mb<x.mb;mb++)for(int l=0;l<x.L;l++)for(auto d:dur[l])best.time+=d+1;
    }
    return best;
}

int main(int argc,char**argv) {
    ios::sync_with_stdio(false);cin.tie(nullptr);In x=read_input();int R=x.N*x.S; i128 H=x.d*x.b/x.k;
    int forceP=0;bool serial=false;for(int i=1;i<argc;i++){string a=argv[i];if(a=="--baseline")serial=true;else if(a.rfind("--force-p=",0)==0)forceP=stoi(a.substr(10));}
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
    if(!serial) {
        vector<int> ord(pcs.size());iota(ord.begin(),ord.end(),0);sort(ord.begin(),ord.end(),[&](int a,int b){return pcs[a].probeTime<pcs[b].probeTime;});
        if(winner!=ord[0])swap(ord[0],ord[find(ord.begin(),ord.end(),winner)-ord.begin()]);
        for(int j=0;j<min(2,(int)ord.size());j++){int id=ord[j];const Cand& c=pcs[id].bestV.P?pcs[id].bestV:pcs[id].maxV;Result r=evaluate(x,c,true,j==0);if(r.time<best.time)best=move(r);}
    }
    const array<string,10> names={"s","disp","gemm","comb","s_bwd","comb_bwd","gemm_dx","gemm_dw","disp_bwd","s_dw"};
    cout<<best.G<<" "<<best.c.P<<"\nPSI\n"<<best.K;for(int j=1;j<best.K;j++)cout<<" "<<best.cuts[j];cout<<"\nMAP\n";
    for(auto&r:best.c.map){for(int e=0;e<x.E;e++)cout<<(e?" ":"")<<r[e];cout<<"\n";}cout<<"SCHEDULE\n";
    if(serial){auto dur=durations(x,best.c);i128 t=0;auto emit=[&](int mb,int l,int op){cout<<dec(t)<<" "<<mb<<":"<<l<<":"<<names[op]<<"\n";t+=dur[l][op]+1;};for(int mb=0;mb<x.mb;mb++){for(int l=0;l<x.L;l++){emit(mb,l,0);emit(mb,l,1);emit(mb,l,2);emit(mb,l,3);}for(int l=x.L-1;l>=0;l--){emit(mb,l,5);emit(mb,l,4);emit(mb,l,6);emit(mb,l,8);emit(mb,l,7);emit(mb,l,9);}}}
    else for(auto&o:best.ops)cout<<dec(o.start)<<" "<<o.mb<<":"<<o.l<<":"<<names[o.op]<<"\n";
}
