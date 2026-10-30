#pragma once
#include "event_scheduler.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <functional>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <tuple>
#include <vector>

namespace local_engine_polish {
using i128=__int128_t;
struct Stats { long long evaluated=0, accepted=0, strict_improve=0, tie_moves=0; int rounds=0; bool exhausted=true; };
inline int engine(int o){return (o==1||o==3||o==5||o==8)?1:0;}
inline int id(int m,int l,int o,int L){return (m*L+l)*10+o;}

// Fixed-layout local search. Each positive-duration operation occupies exactly
// one (group, engine) sequence. DAG and resource constraints are retimed by a
// longest-path pass after each trial ordering.
inline bool polish(int mb,int L,int G,const std::vector<int>& group,
                   const std::vector<std::array<i128,10>>& dur,
                   const std::vector<event_sched::Op>& input,
                   i128 M,i128 U,i128 Ua,i128 residentPerLayer,
                   std::vector<event_sched::Op>& output,i128& bestTime,
                   Stats& stats,std::chrono::steady_clock::time_point deadline,
                   long long maxEvaluations=12000) {
 const int n=mb*L*10; if((int)input.size()!=n)return false;
 std::vector<std::pair<int,int>> baseEdges;
 auto edge=[&](int a,int b){baseEdges.push_back({a,b});};
 for(int m=0;m<mb;m++)for(int l=0;l<L;l++){
  int b=id(m,l,0,L);
  edge(b+1,b+2);edge(b+2,b+3);edge(b,b+3);edge(b+3,b+4);edge(b+3,b+5);
  edge(b+5,b+6);edge(b+5,b+7);edge(b+5,b+9);edge(b+6,b+8);edge(b+4,b+8);
  if(l>0){int p=id(m,l-1,0,L);edge(p+3,b);edge(p+3,b+1);}
  if(l+1<L){int q=id(m,l+1,0,L);edge(q+8,b+4);edge(q+8,b+5);}
 }
 std::vector<i128> orig(n);for(auto&o:input)orig[id(o.mb,o.l,o.op,L)]=o.start;
 using Key=std::pair<int,int>;
 std::map<Key,std::vector<int>> seq;
 for(int m=0;m<mb;m++)for(int l=0;l<L;l++)for(int o=0;o<10;o++)if(dur[l][o]>0)
  seq[{group[l],engine(o)}].push_back(id(m,l,o,L));
 for(auto&kv:seq)std::sort(kv.second.begin(),kv.second.end(),[&](int a,int b){return std::tie(orig[a],a)<std::tie(orig[b],b);});
 std::vector<std::vector<int>> baseOut(n); std::vector<int> baseIndegree(n,0);
 for(auto [a,b]:baseEdges){baseOut[a].push_back(b);baseIndegree[b]++;}
 // Exact official closed-interval resource and memory legality check.
 auto memoryOk=[&](const std::vector<i128>& st,const std::vector<i128>& en){
  auto peakClosed=[](std::vector<std::pair<i128,i128>>& a){std::sort(a.begin(),a.end());std::multiset<i128> ends;int best=0;for(size_t i=0;i<a.size();){size_t j=i;while(j<a.size()&&a[j].first==a[i].first)j++;while(!ends.empty()&&*ends.begin()<a[i].first)ends.erase(ends.begin());best=std::max(best,(int)ends.size()+(int)(j-i));for(size_t k=i;k<j;k++)ends.insert(a[k].second);i=j;}return best;};
  for(int g=0;g<G;g++){
   int layers=0;for(int l=0;l<L;l++)layers+=(group[l]==g);
   std::vector<std::pair<i128,i128>> acts,comms;
   for(int m=0;m<mb;m++)for(int l=0;l<L;l++)if(group[l]==g){int b=id(m,l,0,L);acts.push_back({en[b+3],st[b+4]});for(int o:{1,3,5,8})if(dur[l][o]>0)comms.push_back({st[b+o],en[b+o]});}
   i128 used=(i128)layers*residentPerLayer + U*peakClosed(comms)+Ua*peakClosed(acts);if(used>M)return false;
  }return true;
 };
 auto run=[&](const std::map<Key,std::vector<int>>& s,int gap,std::vector<event_sched::Op>& cand,i128& tm,i128& sumEnd,i128 bestSecondary)->bool{
  std::vector<int> indeg=baseIndegree, next(n,-1); std::vector<unsigned char> nextGap(n,0);
  for(auto&kv:s){auto&v=kv.second;int w=(kv.first.second==1?gap:0);for(size_t j=1;j<v.size();j++){next[v[j-1]]=v[j];nextGap[v[j-1]]=(unsigned char)w;indeg[v[j]]++;}}
  std::priority_queue<int,std::vector<int>,std::greater<int>> q;for(int i=0;i<n;i++)if(!indeg[i])q.push(i);
  std::vector<i128> st(n,0),en(n,0);int done=0;tm=0;sumEnd=0;
  while(!q.empty()){int u=q.top();q.pop();done++;int l=(u/10)%L,o=u%10;en[u]=st[u]+dur[l][o];tm=std::max(tm,en[u]);sumEnd+=en[u];
   for(int v:baseOut[u]){st[v]=std::max(st[v],en[u]);if(--indeg[v]==0)q.push(v);}
   int v=next[u];if(v>=0){st[v]=std::max(st[v],en[u]+nextGap[u]);if(--indeg[v]==0)q.push(v);}
  }
  if(done!=n)return false;
  if(tm>bestTime || (tm==bestTime&&sumEnd>=bestSecondary))return false;
  if(!memoryOk(st,en))return false;
  cand.clear();cand.reserve(n);for(int m=0;m<mb;m++)for(int l=0;l<L;l++)for(int o=0;o<10;o++)cand.push_back({st[id(m,l,o,L)],m,l,o});
  std::sort(cand.begin(),cand.end(),[](auto&a,auto&b){return std::tie(a.start,a.mb,a.l,a.op)<std::tie(b.start,b.mb,b.l,b.op);});return true;
 };

 // Retiming current ordering for each candidate gap; only use it if legal and
 // faster. Try one gap first, then exact block enumeration on the critical path.
 std::map<Key,std::vector<int>> bestSeq=seq; i128 resourceLB=0;for(auto&kv:bestSeq){i128 load=0;for(int z:kv.second)load+=dur[(z/10)%L][z%10];resourceLB=std::max(resourceLB,load);}
 std::vector<event_sched::Op> cand; i128 tm,sumEnd;int chosenGap=0;
 i128 bestSecondary=0;for(auto&o:input)bestSecondary+=o.start+dur[o.l][o.op];output=input;
 for(int gap=0;gap<=1;gap++){if(std::chrono::steady_clock::now()>=deadline)return true;bool ok=run(bestSeq,gap,cand,tm,sumEnd,bestSecondary);stats.evaluated++;if(ok){if(tm<bestTime){bestTime=tm;stats.strict_improve++;}else stats.tie_moves++;bestSecondary=sumEnd;output=cand;chosenGap=gap;stats.accepted++;}}
 // Find a longest path in the reusable base DAG plus current resource chains.
 std::vector<int> indeg=baseIndegree, next(n,-1);std::vector<unsigned char> nextGap(n,0);
 for(auto&kv:bestSeq){auto&v=kv.second;int w=(kv.first.second==1?chosenGap:0);for(size_t j=1;j<v.size();j++){next[v[j-1]]=v[j];nextGap[v[j-1]]=(unsigned char)w;indeg[v[j]]++;}}
 std::vector<int> topo;{std::queue<int> q;for(int i=0;i<n;i++)if(!indeg[i])q.push(i);while(!q.empty()){int u=q.front();q.pop();topo.push_back(u);for(int v:baseOut[u])if(--indeg[v]==0)q.push(v);int v=next[u];if(v>=0&&--indeg[v]==0)q.push(v);}}
 if((int)topo.size()!=n)return true;
 std::vector<i128> start(n,0),finish(n,0);std::vector<int> par(n,-1);for(int u:topo){int l=(u/10)%L,o=u%10;finish[u]=start[u]+dur[l][o];for(int v:baseOut[u]){i128 ns=finish[u];if(ns>start[v])start[v]=ns,par[v]=u;}int v=next[u];if(v>=0){i128 ns=finish[u]+nextGap[u];if(ns>start[v])start[v]=ns,par[v]=u;}}
 int end=0;for(int u=1;u<n;u++)if(finish[u]>finish[end])end=u;std::vector<int> cp;for(int u=end;u>=0;u=par[u])cp.push_back(u);std::reverse(cp.begin(),cp.end());
 std::map<int,std::map<Key,std::vector<int>>> windows;
 for(size_t i=0;i<cp.size();){int u=cp[i],l=(u/10)%L,o=u%10;if(dur[l][o]<=0){i++;continue;}Key k={group[l],engine(o)};size_t j=i+1;while(j<cp.size()){int v=cp[j],vl=(v/10)%L,vo=v%10;if(dur[vl][vo]<=0||Key{group[vl],engine(vo)}!=k)break;j++;}auto it=bestSeq.find(k);if(it!=bestSeq.end()){std::map<int,int> pos;for(int p=0;p<(int)it->second.size();p++)pos[it->second[p]]=p;int lo=it->second.size(),hi=-1;for(size_t z=i;z<j;z++){lo=std::min(lo,pos[cp[z]]);hi=std::max(hi,pos[cp[z]]);}for(int a=lo;a<=hi;a++)for(int len=4;len<=7&&a+len<=hi+1;len++)windows[len][k].push_back(a);}i=j;}
 // Try insertion moves first, interleaving resources and move distances.
 std::set<int> critical(cp.begin(),cp.end());
 auto trySeq=[&](){if(resourceLB>bestTime)return;for(int gap=0;gap<=1;gap++){if(stats.evaluated>=maxEvaluations||std::chrono::steady_clock::now()>=deadline){stats.exhausted=false;return;}std::vector<event_sched::Op> cc;i128 t,s;bool ok=run(bestSeq,gap,cc,t,s,bestSecondary);stats.evaluated++;if(ok){if(t<bestTime){bestTime=t;stats.strict_improve++;}else stats.tie_moves++;bestSecondary=s;output.swap(cc);chosenGap=gap;stats.accepted++;}}};
 auto insertionBase=bestSeq;std::map<Key,std::vector<int>> criticalByResource;for(auto&kv:insertionBase)for(int z:kv.second)if(critical.count(z))criticalByResource[kv.first].push_back(z);
 for(int distance=1;distance<=8&&stats.exhausted;distance++)for(int dir:{-1,1})for(auto&kr:criticalByResource)for(int z:kr.second){if(!stats.exhausted)break;auto&w=bestSeq[kr.first];auto itp=std::find(w.begin(),w.end(),z);if(itp==w.end())continue;int p=itp-w.begin(),q=p+dir*distance;if(q<0||q>=(int)w.size())continue;auto old=w;w.erase(w.begin()+p);w.insert(w.begin()+q,z);long long before=stats.accepted;trySeq();if(stats.accepted==before)w.swap(old);}
 // For each block size, spread the first pass across all resources before
 // completing additional windows. Each window enumerates every permutation.
 for(int len=4;len<=7&&stats.exhausted;len++){auto wit=windows.find(len);if(wit==windows.end())continue;auto&byResource=wit->second;size_t maxWindows=0;for(auto&kv:byResource)maxWindows=std::max(maxWindows,kv.second.size());for(size_t wi=0;wi<maxWindows&&stats.exhausted;wi++)for(auto&kv:byResource){if(wi>=kv.second.size())continue;int a=kv.second[wi];if(stats.evaluated>=maxEvaluations||std::chrono::steady_clock::now()>=deadline){stats.exhausted=false;break;}auto it=bestSeq.find(kv.first);if(it==bestSeq.end()||a+len>(int)it->second.size())continue;auto&v=it->second;auto block=std::vector<int>(v.begin()+a,v.begin()+a+len),perm=block,acceptedBlock=block;std::sort(perm.begin(),perm.end());do{if(perm==block)continue;std::copy(perm.begin(),perm.end(),v.begin()+a);long long before=stats.accepted;trySeq();if(stats.accepted>before)acceptedBlock=perm;else std::copy(acceptedBlock.begin(),acceptedBlock.end(),v.begin()+a);if(!stats.exhausted)break;}while(std::next_permutation(perm.begin(),perm.end()));if(!stats.exhausted)break;}}

 return true;
}
} // namespace local_engine_polish
