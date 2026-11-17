#!/usr/bin/env python3
"""Create a new small dam-break fixture and run an uninterrupted/split comparison."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
from native_restart import need,setval,env
HERE=Path(__file__).resolve().parent

def invoke(*args):subprocess.run([sys.executable,str(HERE/'native_restart.py')]+list(map(str,args)),check=True)
def command(args,log):
    with Path(log).open('x') as f:subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,check=True)
def last(case):return max((case/'.native-restart/snapshots').iterdir(),key=lambda p:float(p.name))
def seal(case):
    s=last(case);invoke('seal','--case',case,'--time',s.name,'--log',case/'native-solver.log','--confirm-stopped');return s

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--ranks',type=int,default=2);p.add_argument('--ras',action='store_true');p.add_argument('--adaptive',action='store_true');a=p.parse_args()
    out=Path(a.output).resolve();need(not out.exists() and out.parent.is_dir(),'Selftest output must be a NEW folder')
    need(a.ranks in (1,2),'Small selftest supports one or two ranks')
    if os.environ.get('SLURM_JOB_ID'):need(int(os.environ.get('SLURM_NTASKS','0'))==a.ranks,'Allocate matching selftest ranks')
    out.mkdir();source=out/'input';source.mkdir()
    template=Path(os.environ['WM_PROJECT_DIR'])/'tutorials/multiphase/interIsoFoam/damBreak'
    for rel in ['constant','system']:shutil.copytree(template/rel,source/rel)
    shutil.copytree(template/'0.orig',source/'0')
    cd=source/'system/controlDict'
    for k,v in {'functions':'{}','endTime':0.02 if a.adaptive else 0.012,'deltaT':0.0002 if a.adaptive else 0.001,'adjustTimeStep':'true' if a.adaptive else 'false','maxDeltaT':0.002,'writeControl':'timeStep','writeInterval':100000}.items():setval(cd,k,v)
    if a.ras:
        (source/'constant/turbulenceProperties').write_text('FoamFile {version 2.0;format ascii;class dictionary;object turbulenceProperties;}\nsimulationType RAS;\nRAS {RASModel kOmegaSST;turbulence on;printCoeffs on;}\n')
        for name,dims,val,wall in [('k','[0 2 -2 0 0 0 0]','0.0001','kqRWallFunction'),('omega','[0 0 -1 0 0 0 0]','10','omegaWallFunction'),('nut','[0 2 -1 0 0 0 0]','1e-5','nutkWallFunction')]:
            text='FoamFile {version 2.0;format ascii;class volScalarField;object '+name+';}\ndimensions '+dims+';\ninternalField uniform '+val+';\nboundaryField {\n'
            for patch in ['leftWall','rightWall','lowerWall']:text+=patch+' {type '+wall+';value uniform '+val+';}\n'
            text+='atmosphere {type zeroGradient;}\ndefaultFaces {type empty;}\n}\n';(source/'0'/name).write_text(text)
        fs=source/'system/fvSolution';fs.write_text(fs.read_text().replace('solvers\n{','solvers\n{\n"(k|omega).*" {solver smoothSolver;smoother symGaussSeidel;tolerance 1e-10;relTol 0;}'))
        fs=source/'system/fvSchemes';fs.write_text(fs.read_text().replace('divSchemes\n{','divSchemes\n{\ndiv(phi,k) Gauss upwind;\ndiv(phi,omega) Gauss upwind;')+'\nwallDist {method meshWave;}\n')
    command(['blockMesh','-case',str(source)],out/'blockMesh.log');command(['setFields','-case',str(source)],out/'setFields.log')
    if a.ranks>1:
        setval(source/'system/decomposeParDict','numberOfSubdomains',2);setval(source/'system/decomposeParDict','coeffs.n','(2 1 1)')
        command(['decomposePar','-case',str(source)],out/'decompose.log')
    for name in ['baseline','split']:
        args=['prepare','--source',source,'--output',out/name,'--ranks',a.ranks,'--confirm-inputs-stable']
        if name=='split':args+=['--stop-at',0.005]
        invoke(*args);invoke('run','--case',out/name)
    reference=seal(out/'baseline');checkpoint=seal(out/'split')
    invoke('prepare-resume','--snapshot',checkpoint,'--output',out/'resumed','--confirm-stopped');invoke('run','--case',out/'resumed');candidate=seal(out/'resumed')
    subprocess.run([sys.executable,str(HERE/'compare_native.py'),'--reference',str(reference),'--candidate',str(candidate),'--output',str(out/'comparison.json')],check=True)
    result={'status':'PASS','runtime':env(),'ranks':a.ranks,'model':'kOmegaSST' if a.ras else 'laminar','adaptive':a.adaptive,'checkpoint':checkpoint.name,'final':reference.name,'comparison':'comparison.json'}
    (out/'test-result.json').write_text(json.dumps(result,indent=2)+'\n');print('SELFTEST PASS',out)
if __name__=='__main__':
    try:main()
    except Exception as e:print('SELFTEST STOP:',e,file=sys.stderr);sys.exit(1)
