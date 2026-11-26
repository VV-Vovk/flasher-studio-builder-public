"""Preflight without executing source code. Emits only validated setup values."""
import argparse,json,tempfile
from pathlib import Path
from build import unpack,detect
import stm32
from native import ENGINES,native_config
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--engine',default='auto');p.add_argument('--target',default='');p.add_argument('--version',default='');p.add_argument('--github-output',type=Path);a=p.parse_args()
with tempfile.TemporaryDirectory() as d:
    root=Path(d)/'src';unpack(a.source,root);engine=detect(root,a.target) if a.engine=='auto' else a.engine
    if engine not in ENGINES|stm32.ENGINES|{'arduino','platformio'}:raise ValueError('Unknown engine')
    target=version=''
    if engine in ENGINES:_,target,version=native_config(root,engine,a.target,a.version)
    if engine in stm32.ENGINES:_,target,version=stm32.config(root,engine,a.target,a.version)
    plan={'engine':engine,'target':target,'version':version};print(json.dumps(plan))
    if a.github_output:
        with a.github_output.open('a') as f:
            for k,v in plan.items():f.write(f'{k}={v}\n')
