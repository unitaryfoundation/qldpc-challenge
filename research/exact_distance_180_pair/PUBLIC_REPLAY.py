#!/usr/bin/env python3
"""Public-code-only independent trial for two n=180 CSS codes.

This runner fetches only publicly available third-party solvers and board data.
Independent tools: exactA/exactB from TimoKellerMath/quantum-error-correction
at pinned commit ae52261bfdbd, public challenge code inputs pinned to
unitaryfoundation/qldpc-challenge commit db19f655b4d2ecfde32c0e16b1bf178d8a5fcac2.

Requires Python3, gcc, network for public GitHub raw files. Does not upload results.
UNKNOWN on timeout/error. This script is a *runner*, not an independent proof.
"""
import os, sys, json, time, hashlib, pathlib, urllib.request, subprocess, re, argparse, shlex
from itertools import combinations

TOOLS_COMMIT='ae52261bfdbd'
BOARD_COMMIT='db19f655b4d2ecfde32c0e16b1bf178d8a5fcac2'
TOOL_BASE=f'https://raw.githubusercontent.com/TimoKellerMath/quantum-error-correction/{TOOLS_COMMIT}/board-certificates-2026-11/src'
BOARD_BASE=f'https://raw.githubusercontent.com/unitaryfoundation/qldpc-challenge/{BOARD_COMMIT}/codes'
SLUGS=['180-18-14','180-20-14']

EXPECTED_SHA256={"180-18-14.json": "805fd91dd45c4af9eaa50c18ef60754702b655fe4cd779576719e15b1fcc63e1", "180-20-14.json": "eec53895ef4c1b72c3ef428ed0445e81403c9370ad14c5b94c7676ef98e2549d", "exactA.c": "2d1f0d1a55d9b9d71eff102eab6f131b4a6ff2da0e973518651877c3c3187856", "exactB.c": "e793e5b34eb60098f9ff72d02f6608e4a7f5975fc8e4f02ada8b5213ad0ae1a1"}

def raw_url(url):
    request=urllib.request.Request(url,headers={'User-Agent':'independent-public-exact-distance-audit/1.0'})
    with urllib.request.urlopen(request,timeout=80) as rsp: return rsp.read()

def sha256(data): return hashlib.sha256(data).hexdigest()

def mask(row):
    x=0
    for q in row: x ^= 1<<q
    return x

def rank(rows):
    piv={}
    for x in rows:
        while x:
            j=x.bit_length()-1
            if j not in piv:
                piv[j]=x
                break
            x ^= piv[j]
    return len(piv)

def in_span(x,rows):
    piv={}
    for r in rows:
        y=r
        while y:
            j=y.bit_length()-1
            if j not in piv:
                piv[j]=y;break
            y ^= piv[j]
    while x:
        j=x.bit_length()-1
        if j not in piv: return False
        x ^= piv[j]
    return True

def write_input(wd,slug,doc):
    n=doc['n'];check=doc['checks']; assert n==180
    hx=[mask(r) for r in check['X']];hz=[mask(r) for r in check['Z']]
    assert len(hx)==90 and len(hz)==90 and all(x.bit_count()==8 for x in hx+hz)
    assert all((x&z).bit_count()%2==0 for x in hx for z in hz)
    rkx,rkz=rank(hx),rank(hz)
    assert n-rkx-rkz==doc['k']
    for s in ['X','Z']:
        witness=doc['distance'][s]['witness']
        assert len(witness)==14 and len(set(witness))==14
        v=mask(witness)
        opposite=hz if s=='X' else hx
        same=hx if s=='X' else hz
        assert all((v&z).bit_count()%2==0 for z in opposite)
        assert not in_span(v,same)
        with open(wd/f'{slug}.{s.lower()}','w') as f:
            f.write(f'{n} {len(check[s])}\n')
            for row in check[s]:f.write(' '.join(map(str,row))+'\n')
    # Public, checkable qubit automorphism, a public code property.
    shift=lambda q:(q//90)*90+(q%90+3)%90
    for s in ['X','Z']:
        rows={tuple(sorted(r)) for r in check[s]}
        assert {tuple(sorted(shift(q) for q in r)) for r in check[s]}==rows
    perm=[shift(i) for i in range(n)]
    assert sorted(perm)==list(range(n))
    with open(wd/f'{slug}.gensA','w') as f:f.write('1\n'+' '.join(map(str,perm))+'\n')
    with open(wd/f'{slug}.gensB','w') as f:f.write(' '.join(map(str,perm))+'\n')
    return {'n':n,'k':doc['k'],'rankX':rkx,'rankZ':rkz,'witness_weight':14,'public_symmetry_check':'PASS'}

def verdict(stdout,returncode,tool):
    matches=[line for line in stdout.splitlines() if line.startswith('RESULT ')]
    if returncode!=0 or len(matches)!=1:return 'UNKNOWN_ERROR',matches[-1] if matches else ''
    line=matches[0]
    if tool=='exactA':
        if re.search(r'\bverdict=none\b',line):return 'EXHAUSTED_NO_LIGHTER_LOGICAL',line
        if re.search(r'\bverdict=found\b',line):return 'LIGHTER_LOGICAL_FOUND',line
    else:
        if 'NODE-LIMIT' in line:return 'UNKNOWN_LIMIT',line
        if re.search(r'\bfound=none\b',line):return 'EXHAUSTED_NO_LIGHTER_LOGICAL',line
        if re.search(r'\bfound=yes\b',line):return 'LIGHTER_LOGICAL_FOUND',line
    return 'UNKNOWN_OUTPUT',line

def run_tool(wd,tool,prefix,side,W,group,timeout_seconds,threads):
    cmd=[str(wd/tool),str(wd/f'{prefix}.x'),str(wd/f'{prefix}.z'),'--side',side,'--W',str(W),
         '--group',str(wd/f'{prefix}.gens{"A" if tool=="exactA" else "B"}'),'--threads',str(threads)]
    if tool=='exactA':cmd+=['--mode','anchor']
    st=time.monotonic()
    try:
        p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout_seconds)
        label,line=verdict(p.stdout,p.returncode,tool)
        out={'status':label,'returncode':p.returncode,'result':line,'time_s':round(time.monotonic()-st,3),
             'command':' '.join(shlex.quote(x) for x in cmd)}
        (wd/f'{prefix}_{side}_{tool}.stdout.log').write_text(p.stdout)
        (wd/f'{prefix}_{side}_{tool}.stderr.log').write_text(p.stderr)
        return out
    except subprocess.TimeoutExpired as e:
        return {'status':'UNKNOWN_TIMEOUT','time_s':round(time.monotonic()-st,3),'timeout_s':timeout_seconds,
                'command':' '.join(shlex.quote(x) for x in cmd)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--timeout',type=int,default=600,help='time limit seconds PER external tool/sector')
    ap.add_argument('--threads',type=int,default=2)
    ap.add_argument('--all',action='store_true',help='both codes, both sides, both independent public tools')
    ap.add_argument('--workdir',default='QDLC_D14_PUBLIC_REPLAY_OUTPUT')
    args=ap.parse_args()
    assert 30<=args.timeout<=86400 and 1<=args.threads<=8
    wd=pathlib.Path(args.workdir).resolve();wd.mkdir(parents=True,exist_ok=True)
    manifest={'version':1,'tools_commit':TOOLS_COMMIT,'board_commit':BOARD_COMMIT,'source_hashes':{},'cases':{},'results':{},'status':'INCOMPLETE'}
    print('Preparing independent third-party public tools. Only externally published tools and board entries are accessed.',flush=True)
    for tool in ['exactA','exactB']:
        raw=raw_url(f'{TOOL_BASE}/{tool}.c')
        if sha256(raw)!=EXPECTED_SHA256[tool+'.c']:raise RuntimeError('Pinned third-party source hash differs: '+tool)
        manifest['source_hashes'][f'{tool}.c']=sha256(raw)
        (wd/f'{tool}.c').write_bytes(raw)
        cmd=['gcc','-O3','-std=gnu11','-pthread','-o',str(wd/tool),str(wd/f'{tool}.c')]
        p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=100)
        if p.returncode!=0:raise RuntimeError(f'GCC compilation error {tool}: {p.stderr[-1500:]}')
    slugs=SLUGS if args.all else [SLUGS[0]]
    for slug in slugs:
        raw=raw_url(f'{BOARD_BASE}/{slug}.json')
        if sha256(raw)!=EXPECTED_SHA256[slug+'.json']:raise RuntimeError('Pinned board input hash differs: '+slug)
        manifest['source_hashes'][f'{slug}.json']=sha256(raw)
        doc=json.loads(raw)
        manifest['cases'][slug]=write_input(wd,slug,doc)
    # Small independent sanity check with public seven-qubit Steane CSS code.
    small='steane7'
    rows=[[0,1,2,3],[0,1,4,5],[0,2,4,6]]
    steane={'n':7,'checks':{'X':rows,'Z':rows}}
    for s in ['X','Z']:
        with open(wd/f'{small}.{s.lower()}','w') as f:
            f.write('7 3\n');f.writelines(' '.join(map(str,row))+'\n' for row in rows)
    # Steane case without group: use tool-specific command.
    for tool in ['exactA','exactB']:
        for w,expected in [(2,'none'),(3,'found')]:
            cmd=[str(wd/tool),str(wd/f'{small}.x'),str(wd/f'{small}.z'),'--side','X','--W',str(w)]
            if tool=='exactA':cmd+=['--mode','anchor']
            p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=60)
            status,line=verdict(p.stdout,p.returncode,tool)
            assert status==('EXHAUSTED_NO_LIGHTER_LOGICAL' if expected=='none' else 'LIGHTER_LOGICAL_FOUND'), (tool,w,status,p.stderr,line)
    print('Steane 7-qubit controls: PASS (both external tools exclude <=2 and find <=3).',flush=True)
    combos=[(slug,side,tool) for slug in slugs for side in ['X','Z'] for tool in ['exactA','exactB']]
    if not args.all:combos=combos[:1]
    for slug,side,tool in combos:
        key=f'{slug}_{side}_{tool}'
        print('START',key,'W=13',flush=True)
        manifest['results'][key]=run_tool(wd,tool,slug,side,13,None,args.timeout,args.threads)
        result=manifest['results'][key]
        print('RESULT',key,result['status'],'seconds',result['time_s'],flush=True)
        (wd/'independent_status.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False))
        if result['status']!='EXHAUSTED_NO_LIGHTER_LOGICAL':
            print('STOP: no certificate for',key,'status',result['status'],flush=True)
            break
    done=len(manifest['results'])==len(combos)
    if done and all(v['status']=='EXHAUSTED_NO_LIGHTER_LOGICAL' for v in manifest['results'].values()):
        manifest['status']='TWO_PUBLIC_SOLVERS_ALL_SECTORS_PASS' if args.all else 'ONE_PUBLIC_SOLVER_ONE_SECTOR_PASS'
    else:manifest['status']='UNKNOWN_OR_COUNTEREXAMPLE_REQUIRES_REVIEW'
    (wd/'independent_status.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False))
    print('FINAL',manifest['status'],flush=True)
    print('Local logs and hashes:',wd,flush=True)
    return 0 if manifest['status'].endswith('PASS') else 2

if __name__=='__main__':sys.exit(main())
