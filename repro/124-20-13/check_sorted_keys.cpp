// Streaming verifier for the primary enumerator's native-uint64 sorted output.
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
int main(int argc,char**argv){
 if(argc!=2)return 2;
 std::ifstream in(argv[1],std::ios::binary);if(!in)return 3;
 std::vector<uint64_t> buf(1<<17);uint64_t count=0,duplicates=0,descending=0,fixed=0,invalid=0,prev=0,minimum=0;
 while(in){
  in.read(reinterpret_cast<char*>(buf.data()),buf.size()*sizeof(uint64_t));auto bytes=in.gcount();if(bytes%8)return 4;
  for(size_t i=0;i<static_cast<size_t>(bytes)/8;i++){
   auto x=buf[i];if(!count)minimum=x;else{duplicates+=(x==prev);descending+=(x<prev);}
   fixed+=((x>>2)|((x&3)<<60))==x;invalid+=(x>>62)!=0;prev=x;count++;
  }
 }
 if(!in.eof())return 5;
 std::cout<<"{\"keys\":"<<count<<",\"duplicates\":"<<duplicates<<",\"descending\":"<<descending<<",\"fixed_syndromes\":"<<fixed<<",\"invalid_high_bits\":"<<invalid<<",\"minimum\":"<<minimum<<",\"maximum\":"<<prev<<"}\n";
 return (count==151623375 && !duplicates && !descending && !fixed && !invalid)?0:1;
}
