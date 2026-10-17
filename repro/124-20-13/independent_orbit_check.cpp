// Independent replay: reverse-lane support ordering; MAXIMUM syndrome rotations.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
#include <chrono>
using V=uint64_t; constexpr V M=(V(1)<<31)-1;
std::array<V,124> C; std::array<V,4>L{};std::vector<V> K;
V exceptional=0, reps=0, trials=0;int weight;
V rot(V x,int s){return ((x>>s)|(x<<(31-s)))&M;}
V rotateS(V s){return ((s<<2)&((V(1)<<62)-1))|(s>>60);}
bool keep(int first){
 // Representatives all have position0 in the first nonempty lane.
 // Choose lexicographically smallest REVERSED tuple among anchored rotations.
 for(int j=1;j<31;++j)if((L[first]>>j)&1){
  for(int t=3;t>=0;--t){V a=rot(L[t],j);if(a<L[t])return false;if(a>L[t])break;}
 }
 return true;
}
void end(int first,V syndrome){
 ++trials;if(!keep(first))return;++reps;
 if(rotateS(syndrome)==syndrome)++exceptional;
 V best=syndrome,s=syndrome;for(int i=1;i<31;++i){s=rotateS(s);best=std::max(best,s);}K.push_back(best);
}
void gen(int first,int start,int left,V syndrome){
 if(left==0){end(first,syndrome);return;}
 for(int i=start;i<=124-left;++i){L[i/31]|=V(1)<<(i%31);gen(first,i+1,left-1,syndrome^C[i]);L[i/31]&=~(V(1)<<(i%31));}
}
V choose(int n,int k){V v=1;for(int i=1;i<=k;i++)v=v*(n+1-i)/i;return v;}
int main(int argc,char**argv){if(argc!=3)return 2;std::ifstream in(argv[1]);for(auto&x:C)if(!(in>>x))return 3;
 int maxw=std::stoi(argv[2]);V total=0;for(int w=1;w<=maxw;++w)total+=choose(124,w)/31;K.reserve(total);
 auto start=std::chrono::steady_clock::now();
 for(weight=1;weight<=maxw;++weight){V r=reps;for(int first=0;first<4;++first){L={0,0,0,0};L[first]=1;gen(first,31*first+1,weight-1,C[31*first]);}std::cout<<"{\"weight\":"<<weight<<",\"actual\":"<<reps-r<<",\"expected\":"<<choose(124,weight)/31<<"}"<<std::endl;if(reps-r!=choose(124,weight)/31)return 4;}
 if(K.size()!=total)return 5;std::sort(K.begin(),K.end());V duplicates=0;for(size_t i=1;i<K.size();++i)duplicates+=(K[i]==K[i-1]);
 std::cout<<"{\"completed\":true,\"entries\":"<<K.size()<<",\"distinct_orbit_syndrome_collisions\":"<<duplicates<<",\"fixed_syndromes\":"<<exceptional<<",\"seconds\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<"}"<<std::endl;
 return (duplicates||exceptional)?1:0;
}
