"""Exact cyclic-orbit meet in the middle; each error orbit represented by errors containing site 0."""
import json,itertools,math,time,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def run(n,u,v,radius):
 t=time.time();a=[1,n-1];b=sorted([u,n-u,v,n-v]);mask=np.uint64((1<<n)-1)
 # a=x+x^-1 has gcd x+1 with x^n+1 for odd n; b even implies rank n-1.
 assert n%2==1 and n<=62
 cols=np.zeros((n,3),dtype=np.uint64)
 for q in range(n):
  sx=sum(1<<((q-j)%n) for j in b);sz=sum(1<<((q-j)%n) for j in a)
  cols[q]=[sx,sz,sx^sz]
 count=1+sum(math.comb(n-1,w-1)*3**w for w in range(1,radius+1));keys=np.empty(count,dtype=np.uint64);keys[0]=0;cursor=1
 for w in range(1,radius+1):
  choices=np.array(list(itertools.product(range(3),repeat=w)),dtype=np.int16)
  labels=np.bitwise_xor.reduce(np.array([1,2,3],np.uint64)[choices],axis=1)
  combos=iter(itertools.combinations(range(1,n),w-1))
  while True:
   cs=list(itertools.islice(combos,2048))
   if not cs:break
   qs=np.column_stack((np.zeros(len(cs),np.int16),np.array(cs,dtype=np.int16).reshape(len(cs),w-1)))
   s=np.zeros((len(qs),len(choices)),np.uint64)
   for j in range(w):s^=cols[qs[:,j,None],choices[None,:,j]]
   smallest=s.copy()
   for shift in range(1,n):
    s=((s<<np.uint64(1))&mask)|(s>>np.uint64(n-1));np.minimum(smallest,s,out=smallest)
   values=(smallest<<np.uint64(2))|labels[None,:];keys[cursor:cursor+values.size]=values.ravel();cursor+=values.size
  print('weight',w,'seconds',round(time.time()-t),flush=True)
 assert cursor==count
 keys.sort();different=0
 for start in range(0,len(keys)-1,1000000):
  end=min(len(keys)-1,start+1000000);a1=keys[start:end];b1=keys[start+1:end+1]
  different+=int(np.count_nonzero(((a1>>np.uint64(2))==(b1>>np.uint64(2)))&(a1!=b1)))
 res={'n':n,'seed_X':a,'seed_Z':b,'radius':radius,'represented_errors':count,'complete_orbit_coverage':True,'different_logical_label_collisions':different,'distance_lower_bound':2*radius+1 if different==0 else None,'seconds':time.time()-t}
 (ROOT/f'certificates/orbit_{n}_{u}_{v}_{radius}.json').write_text(json.dumps(res,indent=2),encoding='utf-8');print(res,flush=True)
if __name__=='__main__':run(*map(int,sys.argv[1:]))
