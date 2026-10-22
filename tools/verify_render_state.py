"""Verify batch ownership, relocated engine addresses, and scoped dictionary maps."""
import json, os, shutil, struct, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
try:
    from build_support import find_zig,compiler_environment
    zig=find_zig();environment=compiler_environment()
except ImportError:
    zig=ROOT/'toolchain/zig/ziglang/zig.exe'
    environment=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(ROOT/'build/zig-cache'))
out=ROOT/'build/render-state-test'
out.mkdir(parents=True,exist_ok=True)
for name in ('fonts/ui.zhf','translations/ui.utf8'):
    target=out/'ExanimaZh'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'build/preview-package/ExanimaZh'/name,target)
subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu',
                '-O2','-Wall','-Wextra','-Werror',str(ROOT/'native/render_state_verify.c'),
                str(ROOT/'native/compatibility.c'),'-lbcrypt','-lopengl32','-o',str(out/'render_state_verify.exe')],
               env=environment,check=True)
cases=[]
def run_case(name,program,args):
    run=subprocess.run([str(program),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
    cases.append({'name':name,'exit_code':run.returncode,'output':run.stdout,'stderr':run.stderr})
run_case('default_layout',out/'render_state_verify.exe',[])
run_case('shifted_layout_guarded',out/'render_state_verify.exe',['--shift','0x10000'])
fixture='zh.test.scope.only\t后退\t123450\nzh.test.scope.fallback\t后退\t123490\nzh.test.scope.fallback\t返回\n'
for mode in ('legacy','mapped','missing','duplicate','collision'):
    case=out/('scope-'+mode)
    for directory in ('ExanimaZh/fonts','ExanimaZh/translations'):(case/directory).mkdir(parents=True,exist_ok=True)
    shutil.copy2(out/'render_state_verify.exe',case/'render_state_verify.exe')
    shutil.copy2(out/'ExanimaZh/fonts/ui.zhf',case/'ExanimaZh/fonts/ui.zhf')
    (case/'ExanimaZh/translations/ui.utf8').write_text(fixture,encoding='utf-8',newline='\n')
    run_case('scope_'+mode,case/'render_state_verify.exe',['--scope-test',mode])
from stage_preview import select
enabled=select()[0]
versions=[version for version in json.loads((ROOT/'data/versions.json').read_text(encoding='utf-8'))['versions']
          if 'steam_build_id' in version]
if not versions:
    raise ValueError('No Steam profile with steam_build_id was found in data/versions.json.')
layout_fields=('font_slot','begin','end','uv','vertex','color','batch_count','gui_slot','current_color')
fallbacks={row['en']:row['zh'] for row in enabled if not row.get('source_rva')}
scoped_rows={row['source_rva']:row for row in enabled if row.get('source_rva')}
profile_fixtures=[]
for version in versions:
    mappings={int(row['legacy_rva'],0):int(row['current_rva'],0) for row in version['scopes']}
    if set(mappings)!=set(scoped_rows):
        raise ValueError(f"Profile scope coverage differs from current dictionary: {version['id']}")
    for scope in version['scopes']:
        if scoped_rows[int(scope['legacy_rva'],0)]['en'].encode('latin-1').hex()!=scope['source_hex']:
            raise ValueError(f"Profile scope text differs from current dictionary: {version['id']}")
    records=[]
    for row in enabled:
        legacy=row.get('source_rva',0)
        current=mappings[legacy] if legacy and version['remap_scopes'] else legacy
        # Compare against editable translation sources, not the loaded runtime dictionary.
        records.append((current,row['en'],row['zh'],current,0))
        if legacy:
            records.append((0,row['en'],fallbacks.get(row['en'],''),0,1))
            if current!=legacy:
                records.append((legacy,row['en'],fallbacks.get(row['en'],''),0,2))
    path=out/f"profile-{version['id']}.bin"
    data=bytearray(b'ZPV1'+struct.pack('<I9I',len(records),*(int(version['layout'][name],0) for name in layout_fields)))
    for placement,en,zh,expected_scope,kind in records:
        source=en.encode('latin-1');expected=zh.encode('utf-8')
        data+=struct.pack('<5I',placement,len(source),len(expected),expected_scope,kind)+source+expected
    path.write_bytes(data)
    run_case('profile_'+version['id'],out/'render_state_verify.exe',['--profile',version['exe_sha256'],'--cases',str(path)])
    profile_fixtures.append({'profile':version['id'],'dictionary_records':len(enabled),'scoped_records':len(scoped_rows),
                             'wrong_pointer_records':sum(record[4]==1 for record in records),
                             'legacy_pointer_records':sum(record[4]==2 for record in records),
                             'layout_fields':len(layout_fields),'fixture':str(path.relative_to(ROOT))})
run_case('unknown_sha_refused',out/'render_state_verify.exe',['--profile','0'*64,'--expect-unknown'])
exit_code=next((case['exit_code'] for case in cases if case['exit_code']),0)
report={'exit_code':exit_code,'output':'\n'.join(case['output'] for case in cases),
        'stderr':'\n'.join(case['stderr'] for case in cases if case['stderr']),'cases':cases,'profile_fixtures':profile_fixtures,
        'scope':'Real Unicode draw and asset-loader code; default and shifted engine mocks plus Steam version layouts; full dictionary output and pointer-scoped fallbacks; guarded legacy pages; unknown SHA rejection; not game visual verification'}
(out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(exit_code)
