// Study helper: apply the bounded grouped-placement search to every layer at P.
#define main included_solver_main
#include "../../solver.cpp"
#undef main

enum SearchStatus { FOUND=0, PROVEN_NO=1, BUDGET=2, UNSUPPORTED=3 };

SearchStatus search_peak(const vector<i128>& slots, int P, int per, i128 cap,
                         grouped_placement::Plan& out, uint64_t budget) {
    using namespace grouped_placement;
    if(P<1||P>32||per<1||per>32||slots.size()!=size_t(P*per))return UNSUPPORTED;
    vector<i128> values=slots;
    if(any_of(values.begin(),values.end(),[](i128 x){return x<0;}))return UNSUPPORTED;
    sort(values.begin(),values.end());values.erase(unique(values.begin(),values.end()),values.end());
    if(values.empty()||values.size()>4)return UNSUPPORTED;
    vector<int> available(values.size());
    for(i128 x:slots)++available[lower_bound(values.begin(),values.end(),x)-values.begin()];
    detail::Search s(P,per,cap,values,available,budget);
    vector<int> pattern(values.size());
    s.enumerate_patterns(0,per,0,pattern);
    if(s.exhausted)return BUDGET;
    if(s.patterns.empty())return PROVEN_NO;
    vector<int> used(values.size());vector<vector<int>> chosen;chosen.reserve(P);
    bool ok=s.dfs(0,0,used,chosen);
    if(s.exhausted)return BUDGET;
    if(!ok)return PROVEN_NO;
    Plan p;p.values=values;p.rank_counts=move(s.solution);p.peak=cap;out=move(p);
    return FOUND;
}

int main(int argc,char**argv){
    if(argc!=2)return 2;int P=atoi(argv[1]);In x=read_input();i128 cost=0;auto map=make_map(x,P,cost);int per=x.E/P;
    for(int l=0;l<x.L;l++){
        auto slots=x.load[l];vector<i128> loads(P);for(int e=0;e<x.E;e++)loads[map[l][e]]+=slots[e];
        i128 cur=*max_element(loads.begin(),loads.end()),total=accumulate(slots.begin(),slots.end(),(i128)0),heavy=*max_element(slots.begin(),slots.end());
        vector<i128> sorted=slots;sort(sorted.begin(),sorted.end());i128 capLB=heavy;for(int i=0;i<per-1;i++)capLB+=sorted[i];
        i128 arithmetic=max(cd(total,P),capLB),lo=arithmetic,hi=cur-1;bool budget=false;grouped_placement::Plan best;bool found=false;int calls=0;uint64_t visited=0;
        if(cur>arithmetic){
            for(int z=0;z<12&&lo<=hi;z++){
                i128 mid=lo+(hi-lo)/2;grouped_placement::Plan trial;++calls;
                SearchStatus s=search_peak(slots,P,per,mid,trial,250000);
                if(s==FOUND){best=move(trial);found=true;hi=mid-1;}
                else if(s==PROVEN_NO)lo=mid+1;
                else if(s==BUDGET){budget=true;break;}
                else {break;}
            }
        }
        if(found){vector<int> row;if(grouped_placement::materialize(slots,best,row))map[l]=move(row);}
        vector<i128> after(P);for(int e=0;e<x.E;e++)after[map[l][e]]+=slots[e];i128 final=*max_element(after.begin(),after.end());
        vector<i128> vals=slots;sort(vals.begin(),vals.end());vals.erase(unique(vals.begin(),vals.end()),vals.end());
        cerr<<"LAYER "<<l<<" T="<<dec(total)<<" types="<<vals.size()<<" make_map="<<dec(cur)<<" arithmeticLB="<<dec(arithmetic)<<" improved="<<(final<cur)<<" final="<<dec(final)<<" budget="<<budget<<" calls="<<calls<<"\n";
    }
    for(const auto&row:map){for(size_t e=0;e<row.size();e++){if(e)cout<<' ';cout<<row[e];}cout<<'\n';}
    return 0;
}
