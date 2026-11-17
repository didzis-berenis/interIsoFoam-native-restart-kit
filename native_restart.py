#!/usr/bin/env python3
"""Static, deterministic Euler interIsoFoam restart kit. Sources are never edited."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
from field_integrity import screen
HERE=Path(__file__).resolve().parent

def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save_new(p,d):
    with Path(p).open('x') as f:json.dump(d,f,indent=2);f.write('\n')
def get(p,key):return subprocess.check_output(['foamDictionary',str(p),'-precision','17','-entry',key,'-value'],universal_newlines=True).strip().rstrip(';')
def setval(p,key,value):subprocess.run(['foamDictionary',str(p),'-precision','17','-entry',key,'-set',str(value)],check=True,stdout=subprocess.DEVNULL)
def cleantext(p):return re.sub(r'/\*.*?\*/|//[^\n]*','',Path(p).read_text(),flags=re.S)
def env():
    binary=shutil.which('interIsoFoam');need(binary,'Load the OpenFOAM environment first')
    need(os.environ.get('WM_PRECISION_OPTION')=='DP' and sys.byteorder=='little','This kit admits double-precision little-endian builds only')
    need(os.environ.get('WM_LABEL_SIZE','32')=='32','This kit admits label32 builds only')
    return {'version':os.environ.get('WM_PROJECT_VERSION'),'options':os.environ.get('WM_OPTIONS'),'solver':str(Path(binary).resolve()),'solver_sha256':sha(binary)}
def roots(case,n):return [case/('processor'+str(i)) for i in range(n)] if n>1 else [case]
def controls(case,required,optional,restore=(),stop=-1,checkpoint=-1,epoch=-1):
    p=case/'system/nativeRestartControls'
    p.write_text('requiredFields ('+' '.join(required)+');\noptionalFields ('+' '.join(optional)+');\nrestore '+('true' if restore else 'false')+';\nrestoreFields ('+' '.join(restore)+');\nstopAtTime '+str(stop)+';\ncheckpointAtTime '+str(checkpoint)+';\nstopEpoch '+str(epoch)+';\n')
def identity(case,n):
    paths=[]
    for folder in [case/'system',case/'constant',case/'0']+sum(([r/'constant',r/'0'] for r in roots(case,n) if r!=case),[]):
        if folder.is_dir():
            for p in folder.rglob('*'):
                if p.is_file() and p.name not in ('nativeRestartControls','NATIVE_STOP','NATIVE_CHECKPOINT'):
                    need(not p.is_symlink(),'Symlink input refused: '+str(p));paths.append(p)
    return {str(p.relative_to(case)):sha(p) for p in paths}
def scope(case,n):
    need(n>0,'Ranks must be positive')
    cd=case/'system/controlDict'
    adaptive=get(cd,'adjustTimeStep').lower() in ('true','yes','on','1')
    wc=get(cd,'writeControl')
    need(not adaptive or wc not in ('adjustable','adjustableRunTime'),'Adaptive stepping with adjustable output shifts its scheduling origin on restart. V1 refuses it; use an independently tested non-adjustable output schedule from the beginning.')
    recon=re.findall(r'\breconstructionScheme\s+([^;]+);',cleantext(case/'system/fvSolution'))
    need(all(r.strip()=='isoAlpha' for r in recon),'Other interface reconstruction schemes require review')
    for parent in (case/'system',case/'constant'):
        for p in parent.glob('*'):
            if p.is_file():
                text=p.read_text(errors='replace')
                need(not re.search(r'#include\s+[\"](?:/|\.\./)',text),'External include must be copied/audited first: '+str(p))
    dy=case/'constant/dynamicMeshDict'
    need(not dy.exists() or get(dy,'dynamicFvMesh')=='staticFvMesh','Dynamic meshes need a separate motion/topology audit; v1 refuses them')
    for name in ('fvOptions','MRFProperties','porosityProperties'):
        need(not (case/'constant'/name).exists() and not (case/'system'/name).exists(),'Extra source/model state requires review: '+name)
    need(get(case/'system/fvSchemes','ddtSchemes.default')=='Euler','V1 admission requires default Euler ddt')
    txt=cleantext(case/'system/fvSchemes');block=get(case/'system/fvSchemes','ddtSchemes')
    need(not re.search(r'\b(backward|CrankNicolson|localEuler|steadyState)\b',block),'Only Euler is admitted in v1')
    initials=[case/'0']+[r/'0' for r in roots(case,n) if r!=case]
    for p in (p for folder in initials for p in folder.glob('*')):
        if p.is_file():need(not re.search(r'\b(coded|codedFixedValue|turbulentInlet|turbulentDFSEMInlet|turbulentDigitalFilterInlet|timeVaryingMappedFixedValue)\b',cleantext(p)),'Stateful/custom boundary requires review: '+str(p))
    tp=case/'constant/turbulenceProperties';model=get(tp,'simulationType')
    required=['U','p_rgh','phi','rho','rhoPhi']
    phases=re.findall(r'[A-Za-z][A-Za-z0-9_]*',get(case/'constant/transportProperties','phases'))
    need(len(phases)==2,'Expected exactly two phase names')
    required+=['alpha.'+p for p in phases]
    if model=='RAS':
        name=get(tp,'RAS.RASModel');need(name=='kOmegaSST','V1 supports laminar and standard RAS kOmegaSST only')
        required+=['k','omega','nut']
    else:need(model=='laminar','LES/other models require a state audit')
    for r in roots(case,n):need((r/'constant/polyMesh').is_dir() and (r/'0').is_dir(),'Missing initial mesh/fields: '+str(r))
    return required,['p','rAU']
def init(a):
    src=Path(a.source).resolve();dst=Path(a.output).resolve()
    need(a.confirm_inputs_stable,'Confirm source system/constant/0 inputs are not being modified')
    need(not dst.exists() and dst.parent.is_dir(),'Output must be a NEW folder with an existing parent')
    scope(src,a.ranks)
    dst.mkdir();(dst/'PREPARATION_INCOMPLETE').write_text('Do not run until native-plan.json exists\n')
    for rel in ['system','constant','0']+sum(([str(r.relative_to(src))+'/constant',str(r.relative_to(src))+'/0'] for r in roots(src,a.ranks) if r!=src),[]):
        p=src/rel
        if p.is_dir():shutil.copytree(p,dst/rel,ignore=shutil.ignore_patterns('dynamicCode','NATIVE_STOP','NATIVE_CHECKPOINT','nativeRestartControls','nativeSnapshot'))
    required,optional=scope(dst,a.ranks)
    cd=dst/'system/controlDict'
    setval(cd,'application','interIsoFoam');setval(cd,'startFrom','startTime');setval(cd,'startTime','0');setval(cd,'stopAt','endTime')
    for k,v in {'purgeWrite':0,'writeFormat':'binary','writeCompression':'off','writePrecision':17,'timePrecision':17,'runTimeModifiable':'true'}.items():setval(cd,k,v)
    # In a NEW case only: insert the hook without touching any live dictionary.
    s=cd.read_text();stripped=re.sub(r'/\*.*?\*/|//[^\n]*',lambda m:' '*len(m.group()),s,flags=re.S);m=re.search(r'\bfunctions\s*\{',stripped)
    need('nativeSnapshot' not in s and 'rescueController' not in s,'Source already contains a rescue hook; review it first')
    s=s[:m.end()]+'\n#include "nativeSnapshot"\n'+s[m.end():] if m else s+'\nfunctions {\n#include "nativeSnapshot"\n}\n'
    (dst/'system/nativeSnapshot').write_bytes((HERE/'nativeSnapshot').read_bytes());cd.write_text(s)
    (dst/'system/nativeReadDict').write_text('FoamFile {version 2.0;format ascii;class dictionary;object nativeReadDict;}\nfunctions {}\n')
    controls(dst,required,optional,stop=a.stop_at,checkpoint=a.checkpoint_at)
    plan={'version':1,'ranks':a.ranks,'source':str(src),'required':required,'optional':optional,'runtime':env(),'inputs':identity(dst,a.ranks)}
    save_new(dst/'native-plan.json',plan);(dst/'PREPARATION_INCOMPLETE').unlink();print('PREPARED',dst)
def check_identity(case,plan):
    need(env()==plan['runtime'],'Runtime/solver differs from preparation; no restart')
    need(identity(case,plan['ranks'])==plan['inputs'],'System/constant inputs changed since preparation; review before restart')
def stopped_job(case):
    import fcntl
    with (case/'native-run.lock').open('a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    record=read(case/'NATIVE_RUN_STARTED.json');old=record.get('job')
    if not old:return
    # Within selftest, the run command has returned and released its case lock.
    # Separate production continuations must observe a terminal previous job.
    if str(old)==os.environ.get('SLURM_JOB_ID'):
        import fcntl
        with (case/'native-run.lock').open('a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return
    row=subprocess.check_output(['sacct','-nP','-j',str(old),'--format=JobID,State'],universal_newlines=True)
    states=[l.split('|')[1].split()[0].rstrip('+') for l in row.splitlines() if l.startswith(str(old)+'|')]
    need(len(states)==1 and states[0] in ('COMPLETED','CANCELLED','FAILED','TIMEOUT','NODE_FAIL','PREEMPTED','OUT_OF_MEMORY'),'Previous exact Slurm job is not confirmed terminal')
    ids=subprocess.check_output(['squeue','-h','-u',os.environ.get('USER',''),'-o','%i'],universal_newlines=True).split()
    need(str(old) not in ids,'Previous job remains in queue')

def seal(a):
    case=Path(a.case).resolve();plan=read(case/'native-plan.json');check_identity(case,plan)
    need(a.confirm_stopped,'Seal only after all source processes have ended');stopped_job(case)
    label=a.time;need(re.fullmatch(r'[0-9.eE+-]+',label),'Invalid exact time label')
    snap=case/'.native-restart/snapshots'/label;need(snap.is_dir(),'Snapshot missing')
    need(not (snap/'SEALED.json').exists(),'Snapshot already sealed; use verify')
    files={};meta=[]
    for rank,r in enumerate(roots(snap,plan['ranks'])):
        folder=r/label;d=read(folder/'native-ready.json')
        need(d['version']==1 and d['rank']==rank and d['ranks']==plan['ranks'] and d['label']==label,'Receipt identity mismatch')
        rootnames={f['root'] for f in d['fields']}
        need(set(plan['required'])<=rootnames,'Required field missing')
        for row in d['fields']:
            name=row['name'];need(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*',name),'Unsafe field name')
            p=folder/name;screen(p)
            with p.open('rb') as f: head=f.read(2048)
            need(('class       '+row['class']) in head.decode(errors='replace') or re.search(rb'\bclass\s+'+row['class'].encode()+rb'\s*;',head),'Wrong field class')
        for p in folder.rglob('*'):
            if p.is_file():files[str(p.relative_to(snap))]=sha(p)
        tp=folder/'uniform/time'
        tm={'value':float(get(tp,'value')),'name':get(tp,'name').strip(chr(34)),'index':int(get(tp,'index')),'deltaT':float(get(tp,'deltaT')),'deltaT0':float(get(tp,'deltaT0'))}
        need(tm['value']==d['time'] and tm['name']==label and tm['index']>0 and tm['deltaT']>0 and tm['deltaT0']>0,'Invalid Time metadata')
        d['time_metadata']=tm
        meta.append(d)
    need(all((d['time'],d['reason'],d['fields'],d['time_metadata'])==(meta[0]['time'],meta[0]['reason'],meta[0]['fields'],meta[0]['time_metadata']) for d in meta),'Ranks disagree')
    need(meta[0]['time']>0,'Time-zero snapshot is not an admitted restart')
    log=Path(a.log).resolve()
    with log.open('rb') as f:
        h=f.read(262144);f.seek(0,2);f.seek(max(0,f.tell()-262144));t=f.read()
    txt=(h+b'\n'+t).decode(errors='replace')
    need(re.search(r'^Case\s*:\s*'+re.escape(str(case))+r'\s*$',txt,re.M),'Wrong solver log case')
    need(re.search(r'^End\s*$',txt,re.M) and meta[0]['reason'] in ('safeStop','final'),'Require clean End and a safeStop/final snapshot')
    need('FOAM FATAL' not in txt,'Fatal error in log')
    save_new(snap/'SEALED.json',{'version':1,'case':str(case),'label':label,'ranks':plan['ranks'],'time':meta[0]['time'],'root_fields':sorted({r['root'] for r in meta[0]['fields']}),'files':files,'plan':plan,'log':str(log),'log_sha256':sha(log)})
    print('SEALED',snap)
def verify(snap):
    d=read(snap/'SEALED.json')
    for rel,digest in d['files'].items():need(sha(snap/rel)==digest,'Snapshot changed: '+rel)
    return d
def resume_prepare(a):
    snap=Path(a.snapshot).resolve();d=verify(snap);src=Path(d['case']);plan=d['plan'];check_identity(src,plan)
    need(a.confirm_stopped,'Confirm old solver and batch job are terminal before preparing continuation');stopped_job(src)
    final=float(a.end_time) if a.end_time is not None else float(get(src/'system/controlDict','endTime'))
    need(final>d['time'],'Checkpoint is already at/end beyond endTime; supply --end-time only for an intentional extension')
    dst=Path(a.output).resolve();need(not dst.exists() and dst.parent.is_dir(),'Output must be a NEW folder')
    dst.mkdir();(dst/'PREPARATION_INCOMPLETE').write_text('Do not run until native-plan.json exists\n')
    for rel in ['system','constant','0']+sum(([str(r.relative_to(src))+'/constant',str(r.relative_to(src))+'/0'] for r in roots(src,plan['ranks']) if r!=src),[]):
        p=src/rel
        if p.is_dir():shutil.copytree(p,dst/rel,ignore=shutil.ignore_patterns('NATIVE_STOP','NATIVE_CHECKPOINT','nativeRestartControls'))
    for r in roots(snap,plan['ranks']):
        rel=r.relative_to(snap)/d['label'];shutil.copytree(snap/rel,dst/rel)
    cd=dst/'system/controlDict';setval(cd,'startFrom','startTime');setval(cd,'startTime',d['label']);setval(cd,'stopAt','endTime')
    if a.end_time is not None:setval(cd,'endTime',a.end_time)
    controls(dst,plan['required'],plan['optional'],restore=d['root_fields'],stop=a.stop_at)
    newer=dict(plan);newer.update(source=str(src),checkpoint=str(snap),inputs=identity(dst,plan['ranks']))
    save_new(dst/'native-plan.json',newer);verify(snap)
    (dst/'PREPARATION_INCOMPLETE').unlink();print('PREPARED RESUME',dst)
def typed_check(case,plan):
    snap=Path(plan['checkpoint']);d=verify(snap)
    paths={str((case/rel)):digest for rel,digest in d['files'].items()}
    need(all(sha(p)==h for p,h in paths.items()),'Copied checkpoint differs from sealed snapshot')
    cmd=['postProcess','-case',str(case),'-time',d['label'],'-fields','('+' '.join(d['root_fields'])+')','-dict',str(case/'system/nativeReadDict'),'-lib','libinterfaceProperties.so','-lib','libincompressibleTurbulenceModels.so']
    if plan['ranks']>1:cmd=['mpirun','-np',str(plan['ranks'])]+cmd+['-parallel']
    with (case/'native-typed-read.log').open('x') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
    text=(case/'native-typed-read.log').read_text(errors='replace')
    need('NATIVE_SNAPSHOT_COMPLETE' not in text,'Reader unexpectedly executed snapshot hook')
    for name in d['root_fields']:
        need(re.search(r'^\s*(?:Reading\s+)?(?:volScalarField|volVectorField|surfaceScalarField|volSymmTensorField):.*(?<![A-Za-z0-9_.])'+re.escape(name)+r'(?![A-Za-z0-9_.])',text,re.M),'Typed reader did not confirm '+name)
    need(all(sha(p)==h for p,h in paths.items()),'Typed reader changed checkpoint files')
    print('TYPED_READ_PASS',flush=True)

def run(a):
    case=Path(a.case).resolve();plan=read(case/'native-plan.json');check_identity(case,plan)
    need(not (case/'PREPARATION_INCOMPLETE').exists(),'Incomplete preparation')
    n=plan['ranks']
    if 'checkpoint' in plan:stopped_job(Path(plan['source']))
    if os.environ.get('SLURM_JOB_ID'):need(int(os.environ.get('SLURM_NTASKS','0'))==n,'MPI allocation does not match case')
    import fcntl
    with (case/'native-run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with (case/'NATIVE_RUN_STARTED.json').open('x') as f:json.dump({'runtime':env(),'job':os.environ.get('SLURM_JOB_ID'),'start':time.time()},f)
        log=case/'native-solver.log';cmd=['interIsoFoam','-case',str(case)]
        if n>1:cmd=['mpirun','-np',str(n)]+cmd+['-parallel']
        # Restore only in the newly prepared case. Output functions get new paths.
        if 'checkpoint' in plan:typed_check(case,plan)
        print('Running:', ' '.join(cmd),flush=True)
        with log.open('x') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
        with log.open('rb') as f:
            f.seek(0,2);f.seek(max(0,f.tell()-262144));txt=f.read().decode(errors='replace')
        need(re.search(r'^End\s*$',txt,re.M),'No clean solver End')
        print('SOLVER_ENDED; seal its exact final snapshot before relying on it',flush=True)
def arm(a):
    case=Path(a.case).resolve();plan=read(case/'native-plan.json');check_identity(case,plan)
    started=read(case/'NATIVE_RUN_STARTED.json')
    need(str(started.get('job'))==str(a.job),'Job does not match this case run record')
    need(a.margin>=1800,'Use at least a 30-minute margin')
    row=subprocess.check_output(['scontrol','show','job','-o',str(a.job)],universal_newlines=True)
    need(re.search(r'\bJobId='+str(a.job)+r'\b',row) and 'JobState=RUNNING' in row,'Exact job is not RUNNING')
    match=re.search(r'\bEndTime=(\S+)',row);need(match,'No Slurm EndTime')
    epoch=int(subprocess.check_output(['date','-d',match[1],'+%s'],universal_newlines=True))-a.margin
    need(epoch>time.time()+600,'Too close to deadline; review a manual safe stop')
    p=case/'system/nativeRestartControls';text=p.read_text()
    text,n=re.subn(r'\bstopEpoch\s+[^;]+;', 'stopEpoch '+str(epoch)+';',text);need(n==1,'Unexpected controls schema')
    tmp=p.with_name('nativeRestartControls.deadline-new')
    with tmp.open('x') as f:f.write(text);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
    save_new(case/('native-deadline-'+str(time.time_ns())+'.json'),{'job':a.job,'stop_epoch':epoch,'margin':a.margin})
    print('ARMED stop_epoch='+str(epoch)+'; decision is made in the solver; keep enough time for snapshot I/O')

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='cmd');s.required=True
    q=s.add_parser('prepare');q.add_argument('--source',required=True);q.add_argument('--output',required=True);q.add_argument('--ranks',type=int,default=1);q.add_argument('--confirm-inputs-stable',action='store_true');q.add_argument('--stop-at',type=float,default=-1);q.add_argument('--checkpoint-at',type=float,default=-1)
    q=s.add_parser('request');q.add_argument('--case',required=True);q.add_argument('action',choices=['checkpoint','stop'])
    q=s.add_parser('seal');q.add_argument('--case',required=True);q.add_argument('--time',required=True);q.add_argument('--log',required=True);q.add_argument('--confirm-stopped',action='store_true')
    q=s.add_parser('verify');q.add_argument('--snapshot',required=True)
    q=s.add_parser('prepare-resume');q.add_argument('--snapshot',required=True);q.add_argument('--output',required=True);q.add_argument('--confirm-stopped',action='store_true');q.add_argument('--end-time');q.add_argument('--stop-at',type=float,default=-1)
    q=s.add_parser('arm-deadline');q.add_argument('--case',required=True);q.add_argument('--job',required=True,type=int);q.add_argument('--margin',type=int,default=7200)
    q=s.add_parser('run');q.add_argument('--case',required=True)
    a=p.parse_args()
    if a.cmd=='prepare':init(a)
    elif a.cmd=='seal':seal(a)
    elif a.cmd=='verify':verify(Path(a.snapshot).resolve());print('HASH_VERIFIED')
    elif a.cmd=='prepare-resume':resume_prepare(a)
    elif a.cmd=='run':run(a)
    elif a.cmd=='arm-deadline':arm(a)
    elif a.cmd=='request':
        case=Path(a.case).resolve();need((case/'native-plan.json').is_file(),'Not a prepared native-kit case')
        with (case/'system'/('NATIVE_STOP' if a.action=='stop' else 'NATIVE_CHECKPOINT')).open('x') as f:f.write('requested\n')
        print('REQUESTED',a.action)
if __name__=='__main__':
    try:main()
    except Exception as e:print('STOP:',e,file=sys.stderr);sys.exit(1)
