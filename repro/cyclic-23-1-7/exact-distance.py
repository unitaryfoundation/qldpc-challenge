"""Requires qldpc==0.3.3. Run from any directory with the adjacent candidate JSON."""
import json
from pathlib import Path
import numpy as np
from qldpc.codes import QuditCode, QuantumGolayCode

doc=json.loads((Path(__file__).resolve().parents[2]/'codes/23-1-7-cyclic.json').read_text())
n=doc['n']; S=np.zeros((len(doc['checks']['S']),2*n),dtype=int)
for i,row in enumerate(doc['checks']['S']):
    S[i,row['X']]=1
    S[i,[n+j for j in row['Z']]]=1
code=QuditCode(S,field=2,is_subsystem_code=False)
assert code.get_logical_ops().shape==(2,46)
assert code.get_stabilizer_ops(canonicalized=True).shape==(22,46)
print('Exact Pauli distance:',code.get_distance_exact(cutoff=1))
for label,c in [('candidate',code),('quantum Golay',QuantumGolayCode())]:
    words=np.zeros(1,dtype=np.uint64)
    for row in np.asarray(c.get_stabilizer_ops(canonicalized=True),dtype=int):
        v=np.uint64(sum(int(x)<<j for j,x in enumerate(row)))
        words=np.concatenate((words,words^v))
    support=(words&np.uint64((1<<n)-1))|(words>>np.uint64(n))
    counts=np.bincount(np.bitwise_count(support),minlength=n+1)
    print(label,'stabilizer weight counts:',counts.tolist())
