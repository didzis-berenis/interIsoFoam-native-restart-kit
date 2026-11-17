#!/usr/bin/env python3
"""Compare common native snapshot fields, including written patch values."""
import argparse,array,json,math,re,sys
from pathlib import Path
from native_restart import verify,need,save_new,roots
def numbers(path):
    b=Path(path).read_bytes(); binary=bool(re.search(rb'format\s+binary\s*;',b[:2048]))
    tokens=re.compile(rb'\bnonuniform\s+List<(scalar|vector|sphericalTensor|symmTensor|tensor)>\s+(\d+)\s*\(|\buniform\s+([^;]+);')
    comp={b'scalar':1,b'vector':3,b'sphericalTensor':1,b'symmTensor':6,b'tensor':9}
    pos=0; out=[]
    while True:
        m=tokens.search(b,pos)
        if not m: break
        if m[3] is not None:
            values=[float(v) for v in m[3].replace(b'(',b' ').replace(b')',b' ').split()]
            out.append(('uniform',values));pos=m.end();continue
        count=int(m[2])*comp[m[1]]; start=m.end()
        if binary:
            end=start+count*8; values=array.array('d');values.frombytes(b[start:end])
            if sys.byteorder!='little': values.byteswap()
            pos=end+1
        else:
            end=b.index(b';',start); values=[float(v) for v in b[start:end].replace(b'(',b' ').replace(b')',b' ').split()];pos=end+1
        if len(values)!=count: raise RuntimeError('Array count mismatch')
        out.append((m[1].decode(),values))
    return out

def metric(left,right,atol,rtol):
    if len(left)!=len(right): raise RuntimeError('Field schema changed; no comparison claimed')
    maximum=0.; total=0.; ref=0.; count=0; failed=0
    for (ka,a),(kb,b) in zip(left,right):
        if ka!=kb or len(a)!=len(b): raise RuntimeError('Field storage schema changed; no comparison claimed')
        for x,y in zip(a,b):
            if not math.isfinite(x) or not math.isfinite(y): raise RuntimeError('Nonfinite comparison value')
            d=abs(x-y);maximum=max(maximum,d);total+=d*d;ref+=x*x;count+=1
            failed+=d>atol+rtol*abs(x)
    return {'max_abs':maximum,'rms_abs':math.sqrt(total/max(1,count)),
            'relative_l2':math.sqrt(total/ref) if ref else None,'values':count,'outside_tolerance':failed}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True);p.add_argument('--candidate',required=True);p.add_argument('--output',required=True)
    p.add_argument('--atol',type=float,default=1e-12);p.add_argument('--rtol',type=float,default=1e-8);a=p.parse_args()
    left=Path(a.reference).resolve();right=Path(a.candidate).resolve();x=verify(left);y=verify(right)
    need(x['ranks']==y['ranks'] and x['time']==y['time'],'Different ranks or physical times')
    need(x['plan']['runtime']==y['plan']['runtime'],'Different solver/runtime')
    need(x['root_fields']==y['root_fields'],'Different primary/reference field sets')
    result={'status':'PASS','atol':a.atol,'rtol':a.rtol,'reference':str(left),'candidate':str(right),'fields':[],'extra_histories':[]}
    for rank,(l,r) in enumerate(zip(roots(left,x['ranks']),roots(right,y['ranks']))):
        ld=l/x['label'];rd=r/y['label']
        lm={f['name']:f for f in json.loads((ld/'native-ready.json').read_text())['fields']}
        rm={f['name']:f for f in json.loads((rd/'native-ready.json').read_text())['fields']}
        # Startup may allocate extra deep history; report it instead of treating it as missing physical state.
        result['extra_histories'].append({'rank':rank,'reference_only':sorted(set(lm)-set(rm)),'candidate_only':sorted(set(rm)-set(lm))})
        for name in sorted(set(lm)&set(rm)):
            need(lm[name]['class']==rm[name]['class'],'Field class changed')
            row=metric(numbers(ld/name),numbers(rd/name),a.atol,a.rtol);row.update(rank=rank,field=name)
            result['fields'].append(row)
            if row['outside_tolerance']:result['status']='FAIL'
    save_new(Path(a.output),result)
    print(result['status'],'field/rank comparisons:',len(result['fields']),'max_abs:',max(r['max_abs'] for r in result['fields']))
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('STOP:',e,file=sys.stderr);sys.exit(2)
