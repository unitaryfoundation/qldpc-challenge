// Exhaustive cyclic-orbit syndrome collision test. Standalone C++17.
// Input: 124 binary syndrome columns in type-major order, as unsigned integers.
// Output: exact per-weight representative counts and all repeated syndrome keys.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
#include <string>
using U=uint64_t;
constexpr U MASK62=(U(1)<<62)-1;
constexpr uint32_t MASK31=(uint32_t(1)<<31)-1;
U col[124]; std::vector<U> keys; std::array<uint32_t,4> lanes{};
std::array<int,6> chosen{}; uint64_t leaves=0, kept=0, exceptional=0;
std::ofstream exc;
inline uint32_t r31(uint32_t a,int p){return ((a>>p)|(U(a)<<(31-p)))&MASK31;}
inline U r62(U a){return (a>>2)|((a&3)<<60);}
inline bool canonical(int t){
 uint32_t rem=lanes[t]&~1u;
 while(rem){int p=__builtin_ctz(rem);rem&=rem-1;
  for(int j=t;j<4;j++){auto r=r31(lanes[j],p);if(r<lanes[j])return false;if(r>lanes[j])break;}
 }
 return true;
}
inline U key(U s){U best=s;for(int j=1;j<31;j++){s=r62(s);if(s<best)best=s;}return best;}
void visit(int t,int w,U s){
 ++leaves;if(!canonical(t))return;++kept;
 if(r62(s)==s){++exceptional;exc<<"{\"weight\":"<<w<<",\"syndrome\":"<<s<<",\"type_major_support\":[";for(int k=0;k<w;k++)exc<<(k?",":"")<<chosen[k];exc<<"]}\n";}
 keys.push_back(key(s));
}
void rec(int t,int w,int pos,int start,U s){
 if(pos==w){visit(t,w,s);return;}
 for(int k=start;k<=124-(w-pos);k++){
  chosen[pos]=k;lanes[k/31]^=1u<<(k%31);rec(t,w,pos+1,k+1,s^col[k]);lanes[k/31]^=1u<<(k%31);
 }
}
uint64_t choose(int n,int k){uint64_t a=1;for(int i=1;i<=k;i++)a=a*(n-i+1)/i;return a;}
int main(int argc,char**argv){
 if(argc<3){std::cerr<<"usage: orbit_mitm columns.txt output_prefix [max_halfweight=6]\n";return 2;}
 std::ifstream f(argv[1]);for(int i=0;i<124;i++){if(!(f>>col[i]))return 3;}
 std::string prefix=argv[2];int maxw=argc>3?std::stoi(argv[3]):6;uint64_t total=0;
 for(int w=1;w<=maxw;w++)total+=choose(124,w)/31;
 keys.reserve(total);exc.open(prefix+"_exceptions.jsonl");auto start=std::chrono::steady_clock::now();
 for(int w=1;w<=maxw;w++){
  uint64_t prev=kept,pl=leaves;
  for(int t=0;t<4;t++){lanes.fill(0);lanes[t]=1;chosen[0]=31*t;rec(t,w,1,31*t+1,col[31*t]);}
  auto sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
  uint64_t expected=choose(124,w)/31;
  std::cout<<"{\"stage\":\"enumerate\",\"weight\":"<<w<<",\"representatives\":"<<kept-prev<<",\"expected\":"<<expected<<",\"anchored_leaves\":"<<leaves-pl<<",\"seconds\":"<<sec<<"}"<<std::endl;
  if(kept-prev!=expected){std::cerr<<"COUNT MISMATCH\n";return 4;}
 }
 std::cout<<"{\"stage\":\"sort_start\",\"keys\":"<<keys.size()<<",\"bytes\":"<<keys.size()*8<<"}"<<std::endl;
 std::sort(keys.begin(),keys.end());
 std::ofstream duplicates(prefix+"_duplicates.txt");uint64_t duplicate_pairs=0,duplicate_groups=0,max_multiplicity=0;
 for(size_t i=0;i<keys.size();){size_t j=i+1;while(j<keys.size()&&keys[j]==keys[i])j++;if(j-i>1){duplicate_groups++;duplicate_pairs+=(j-i)*(j-i-1)/2;max_multiplicity=std::max<U>(max_multiplicity,j-i);duplicates<<keys[i]<<" "<<j-i<<"\n";}i=j;}
 // Noncryptographic replay digest; use sha256sum on the saved sorted key file too.
 U digest=1469598103934665603ull;for(U x:keys){for(int j=0;j<8;j++){digest^=(x>>(8*j))&255;digest*=1099511628211ull;}}
 std::ofstream out(prefix+"_sorted_keys.bin",std::ios::binary);out.write(reinterpret_cast<const char*>(keys.data()),keys.size()*8);out.close();
 auto sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
 std::cout<<"{\"stage\":\"complete\",\"keys\":"<<keys.size()<<",\"duplicate_groups\":"<<duplicate_groups<<",\"duplicate_pairs\":"<<duplicate_pairs<<",\"max_multiplicity\":"<<max_multiplicity<<",\"exceptional_fixed_syndromes\":"<<exceptional<<",\"fnv1a64\":"<<digest<<",\"seconds\":"<<sec<<"}"<<std::endl;
}
