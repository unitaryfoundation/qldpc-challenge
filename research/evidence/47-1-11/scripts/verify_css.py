import json
from pathlib import Path
from symplectic import basis,contains
R=Path(__file__).resolve().parents[1]
for name in ['47']:
 c=json.loads((R/f'codes/{name}.json').read_text());n=c['n'];rows=[sum(1<<q for q in r['X'])|sum(1<<(n+q) for q in r['Z']) for r in c['checks']['S']];b=basis(rows);assert len(b)==n-c['k'];cert=json.loads((R/f'certificates/css_{name}.json').read_text());lhs=rhs=0
 for e in cert['certificate_equations']:
  s=e['source_stabilizer'];t=e['annihilator'];assert contains(s,b) and all((t&r).bit_count()%2==0 for r in rows);co=ri=0
  for q in range(n):
   x=(s>>q)&1;z=(s>>(q+n))&1;p=(t>>q)&1;v=(t>>(q+n))&1;co^=((p*x)^(v*z))<<(3*q);co^=(p*z)<<(3*q+1);co^=(v*x)<<(3*q+2);ri^=v*z
  assert co==e['coefficient_mask'] and ri==e['rhs'];lhs^=co;rhs^=ri
 assert lhs==0 and rhs==1
print('PASS additional k>1 CSS certificates')
(R/'certificates/k_css_audit.json').write_text(json.dumps({'status':'PASS','codes':['47']},indent=2),encoding='utf-8')
