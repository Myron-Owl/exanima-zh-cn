"""Build with the pinned, project-local Zig compiler; no global SDK required."""
from pathlib import Path
import subprocess
import hashlib
import json
from build_support import find_zig,compiler_environment
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/native'
OUT.mkdir(parents=True,exist_ok=True)
env=compiler_environment()
zig=find_zig()
for source,name,libs in [('proxy.c','winmm.dll',[]),('runtime.c','ExanimaZh.dll',[str(ROOT/'native/unicode.c'),'-lbcrypt','-lopengl32'])]:
    command=[str(zig),'cc','-target','x86_64-windows-gnu','-shared','-O2','-g','-Wall','-Wextra',
             '-Werror',str(ROOT/'native'/source),'-o',str(OUT/name),*libs]
    subprocess.run(command,env=env,check=True,cwd=ROOT)
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.dll')}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest,indent=2))
