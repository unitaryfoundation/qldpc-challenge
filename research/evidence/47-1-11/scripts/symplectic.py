"""Exact, independent binary symplectic utilities. Python standard library only.

A Pauli is the integer x | (z << n). Signed Paulis use (v,p) = i**p X**x Z**z.
No qldpc or challenge helper is imported.
"""
import json
from pathlib import Path
from math import comb
ROOT=Path(__file__).resolve().parent
def load():
    d=json.loads((ROOT/'data/candidate.json').read_text());n=d['n']
    rows=[sum(1<<j for j in r['X']) | sum(1<<(n+j) for j in r['Z']) for r in d['checks']['S']]
    return n,rows
def split(v,n):return v&((1<<n)-1),v>>n
def support(v,n):
    x,z=split(v,n);return x|z
def weight(v,n):return support(v,n).bit_count()
def symp(v,w,n):
    x,z=split(v,n);a,b=split(w,n);return ((x&b).bit_count()+(z&a).bit_count())%2
def basis(rows):
    piv={}
    for v in rows:
        while v:
            p=v.bit_length()-1
            if p not in piv:piv[p]=v;break
            v^=piv[p]
    return [piv[p] for p in sorted(piv,reverse=True)]
def contains(v,bs):
    for r in bs:
        if v>>(r.bit_length()-1)&1:v^=r
    return v==0
def nullspace(rows,width):
    bs=basis(rows);piv={r.bit_length()-1 for r in bs};out=[]
    for j in range(width):
        if j in piv:continue
        v=1<<j
        for r in reversed(bs):
            if (v&r).bit_count()%2:v^=1<<(r.bit_length()-1)
        assert all((v&r).bit_count()%2==0 for r in rows);out.append(v)
    return out
def words_gray(bs):
    v=0;yield v
    for i in range(1,1<<len(bs)):
        v^=bs[(i&-i).bit_length()-1];yield v
def spectrum(rows,n):
    bs=basis(rows);counts=[0]*(n+1);minimum=n+1;mins=[]
    for v in words_gray(bs):
        w=weight(v,n);counts[w]+=1
        if v and w<minimum:minimum=w;mins=[v]
        elif v and w==minimum:mins.append(v)
    return {'rank':len(bs),'counts':counts,'minimum':minimum,'minimal_elements':mins}
def dual_counts(A,n):
    """Additive GF(4) / symplectic MacWilliams transform, exact integer arithmetic."""
    size=sum(A);B=[]
    for j in range(n+1):
        val=0
        for i,c in enumerate(A):
            K=sum((-1)**t*3**(j-t)*comb(i,t)*comb(n-i,j-t)
                  for t in range(max(0,j-(n-i)),min(i,j)+1))
            val+=c*K
        assert val%size==0 and val>=0;B.append(val//size)
    return B
def describe(v,n):
    x,z=split(v,n)
    return {'X':[j for j in range(n) if x>>j&1 and not z>>j&1],
            'Y':[j for j in range(n) if x>>j&1 and z>>j&1],
            'Z':[j for j in range(n) if z>>j&1 and not x>>j&1],
            'support':[j for j in range(n) if (x|z)>>j&1]}
def axis(v,j,n):return ((v>>j)&1)+2*((v>>(n+j))&1) # 1 X, 2 Z, 3 Y
def permute(v,p,n):
    x,z=split(v,n)
    return sum(((x>>j)&1)<<p[j] for j in range(n)) | sum(((z>>j)&1)<<(n+p[j]) for j in range(n))
def local(v,maps,n):
    out=0
    for j,m in enumerate(maps):
        t=axis(v,j,n)
        if t:
            q=m[t-1];out|=(q&1)<<j;out|=((q>>1)&1)<<(n+j)
    return out
def multiply(a,b,n):
    v,p=a;w,q=b;x,z=split(v,n);xx,zz=split(w,n)
    return v^w,(p+q+2*(z&xx).bit_count())%4
def signed_product(rows,n):
    out=(0,0)
    for r in rows:out=multiply(out,r,n)
    return out
def write(name,obj):
    p=ROOT/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(json.dumps(obj,indent=2)+'\n')
def mm(A,B):return [[sum(a*b for a,b in zip(row,col)) for col in zip(*B)] for row in A]
def cyclic_shift(v,t,n):return permute(v,[(i+t)%n for i in range(n)],n)
def golay_rows():
    # Classical Golay g; even subcode has generator (1+x)g.
    g=sum(1<<j for j in [0,1,5,6,7,9,11]);h=g^(g<<1)
    C=[h<<i for i in range(11)]
    return C,C+[v<<23 for v in C]
