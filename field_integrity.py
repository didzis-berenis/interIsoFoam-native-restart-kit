"""Strict finite-value/framing screen for uncompressed OpenFOAM fields.

Structural dictionary parsing remains a separate OpenFOAM check. No mutations.
"""
import array
import math
from pathlib import Path
import re
import sys

LIST = re.compile(rb'nonuniform\s+List<(scalar|vector|sphericalTensor|symmTensor|tensor)>\s+(\d+)\s*\(')
COMP = {b'scalar':1,b'vector':3,b'sphericalTensor':1,b'symmTensor':6,b'tensor':9}

def screen(path, expected_internal=None):
    b=Path(path).read_bytes()
    if not re.search(rb'FoamFile\s*\{',b[:2048]): raise ValueError('missing FoamFile header')
    binary=bool(re.search(rb'format\s+binary\s*;',b[:2048]))
    if binary and not re.search(rb'arch\s+"LSB;label=32;scalar=64"',b[:2048]):
        raise ValueError('unsupported binary architecture')
    pos=0; cleaned=[]; total=0; internal_count=None
    while True:
        m=LIST.search(b,pos)
        if not m: cleaned.append(b[pos:]);break
        cleaned.append(b[pos:m.start()]);n=int(m[2]);c=COMP[m[1]];start=m.end()
        isinternal=bool(re.search(rb'internalField\s*$',b[max(0,m.start()-80):m.start()]))
        if binary:
            end=start+n*c*8
            if end>=len(b) or b[end:end+1]!=b')':raise ValueError('truncated/misframed binary list')
            values=array.array('d');values.frombytes(b[start:end])
            if sys.byteorder!='little':values.byteswap()
            pos=end+1
        else:
            end=b.find(b';',start)
            if end<0:raise ValueError('unterminated ASCII list')
            payload=b[start:end].strip()
            if not payload.endswith(b')'):raise ValueError('unterminated ASCII list')
            toks=payload[:-1].replace(b'(',b' ').replace(b')',b' ').split()
            values=[float(v) for v in toks]
            if len(values)!=n*c:raise ValueError('ASCII list length mismatch')
            pos=end
        if not all(math.isfinite(v) for v in values):raise ValueError('nonfinite field data')
        if isinternal:
            internal_count=n
            if expected_internal is not None and n!=expected_internal:raise ValueError('internal field count != mesh count')
        total+=n*c;cleaned.append(b'nonuniform List<'+m[1]+b'> 0 ()')
    text=b''.join(cleaned)
    if not re.search(rb'internalField\s+(?:uniform|nonuniform)',text):raise ValueError('missing internalField')
    if b'boundaryField' not in text:raise ValueError('missing boundaryField')
    for m in re.finditer(rb'\buniform\s+([^;]+);',text):
        vals=m[1].replace(b'(',b' ').replace(b')',b' ').split()
        if not vals or not all(math.isfinite(float(v)) for v in vals):raise ValueError('invalid uniform value')
    if not text.rstrip().endswith(b'// ************************************************************************* //'):
        raise ValueError('missing native field footer; output may be partial')
    return {'scalars_checked':total,'internal_count':internal_count,'bytes':len(b)}

def mesh_list_count(path):
    b=Path(path).read_bytes();end=b.find(b'}')
    m=re.search(rb'\s(\d+)\s*\(',b[end+1:])
    if not m:raise ValueError('missing mesh list size')
    return int(m[1])

if __name__=='__main__':
    import json
    print(json.dumps(screen(sys.argv[1])))
