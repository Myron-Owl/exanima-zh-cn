"""Regression test: completed image/text batches must not be submitted again."""
import json, os, shutil, subprocess
from pathlib import Path
from build_support import find_zig,compiler_environment
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'build/render-state-test'
out.mkdir(parents=True,exist_ok=True)
for name in ('fonts/ui.zhf','translations/ui.utf8'):
    target=out/'ExanimaZh'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'build/preview-package/ExanimaZh'/name,target)
subprocess.run([str(find_zig()),'cc','-target','x86_64-windows-gnu',
                '-O2','-Wall','-Wextra','-Werror',str(ROOT/'native/render_state_verify.c'),
                '-lopengl32','-o',str(out/'render_state_verify.exe')],
               env=compiler_environment(),check=True)
run=subprocess.run([str(out/'render_state_verify.exe')],capture_output=True,text=True,timeout=20)
report={'exit_code':run.returncode,'output':run.stdout,'stderr':run.stderr,
        'scope':'Real Unicode draw code, mocked GL and verified engine Begin/End semantics; not game visual verification'}
(out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(run.returncode)
