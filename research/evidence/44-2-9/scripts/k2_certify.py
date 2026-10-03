import sys,json,itertools,math,time
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'scripts'));from symplectic import basis,nullspace,contains,symp
r=next(x for x in json.loads((R/'raw_data/even_search.json').read_text()) if x['n']==44 and x['upper_bound']==9);n=r['n'];checks=[{'X':sorted((q+s)%n for q in r['a']),'Z':sorted((q+s)%n for q in r['b'])} for s in range(n)];rows=basis([sum(1<<q for q in p['X'])|sum(1<<(n+q) for q in p['Z']) for p in checks]);k=n-len(rows);mask=(1<<n)-1;normal=nullspace([(v>>n)|((v&mask)<<n) for v in rows],2*n);span=rows[:];logs=[]
for v in normal:
 if not contains(v,span):logs.append(v);span=basis(span+[v])
assert len(logs)==2*k;bits=2*k;cols=np.array([[sum(symp(p,s,n)<<i for i,s in enumerate(rows))*(1<<bits)+sum(symp(p,s,n)<<i for i,s in enumerate(logs)) for p in [1<<q,1<<(n+q),(1<<q)|(1<<(n+q))]] for q in range(n)],np.uint64)
keys=[np.array([0],np.uint64)]
for w in range(1,5):
 qs=np.array(list(itertools.combinations(range(n),w)));v=np.zeros((len(qs),3**w),np.uint64)
 for j,ps in enumerate(itertools.product(range(3),repeat=w)):
  for i,p in enumerate(ps):v[:,j]^=cols[qs[:,i],p]
 keys.append(v.ravel())
a=np.concatenate(keys);a.sort();bad=int(np.count_nonzero((a[:-1]>>np.uint64(bits)==a[1:]>>np.uint64(bits))&(a[:-1]!=a[1:])))
assert not bad
p=r['witness'];w=sum(1<<q for q in p['X'])|sum(1<<(n+q) for q in p['Z']);assert all(symp(w,s,n)==0 for s in rows) and any(symp(w,s,n) for s in logs)
out={'n':n,'k':k,'rank':len(rows),'distance':9,'status':'EXACT_VERIFIED','checks':{'S':checks},'witness':p,'logical_quotient_basis':logs,'errors_enumerated':len(a),'different_logical_label_collisions':bad,'a':r['a'],'b':r['b']};(R/'codes/44_k2.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print({k:v for k,v in out.items() if k not in ['checks','logical_quotient_basis']})
