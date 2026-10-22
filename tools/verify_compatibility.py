"""Native automatic-detection regression tests using owned synthetic PE fixtures.

Normal verification does not need a game executable. --game-exe optionally checks
an actual EXE through the same detector, without executing or modifying that EXE.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,struct,subprocess,sys
from compile_compatibility import compile_data,contract_hash
from build_support import find_zig,compiler_environment,ROOT

OUT=ROOT/'build/compatibility-tests'
BASE=0x140000000
LAYOUT_NAMES=('font_slot','begin','end','uv','vertex','color','batch_count','gui_slot','current_color')


def synthetic(template,profile):
    # These tiny owned test functions are inspected, never executed as game code.
    sections=[(b'.text',0x1000,0x4000,0x400,0x60000000),
              (b'.rdata',0x5000,0x2000,0x4400,0x40000000),
              (b'.data',0x7000,0x6000,0x6400,0xc0000000),
              (b'.pdata',0xe000,0x1000,0xc400,0x40000000)]
    data=bytearray(0xd400)
    data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,0x80)
    data[0x80:0x84]=b'PE\0\0';struct.pack_into('<HH',data,0x84,0x8664,len(sections))
    struct.pack_into('<HH',data,0x94,0xf0,0x22)
    opt=0x98;struct.pack_into('<H',data,opt,0x20b);struct.pack_into('<Q',data,opt+24,BASE)
    struct.pack_into('<II',data,opt+32,0x1000,0x200);struct.pack_into('<II',data,opt+56,0x10000,0x400)
    struct.pack_into('<I',data,opt+108,16)
    for index,(name,rva,size,raw,flags) in enumerate(sections):
        at=opt+0xf0+index*40;data[at:at+8]=name.ljust(8,b'\0')
        struct.pack_into('<4I',data,at+8,size,rva,size,raw);struct.pack_into('<I',data,at+36,flags)
    def offset(rva):
        for _,start,size,raw,_ in sections:
            if start<=rva<start+size:return raw+rva-start
        raise ValueError(hex(rva))
    model=copy.deepcopy(template);nodes=model['functions'];count=len(nodes)
    rvas=[0x1100+n*0x100 for n in range(count)]
    globals_=[0x7100+n*8 for n in range(4)]
    old_targets=[n['rva'] for n in nodes]+[int(profile['layout'][name],0) for name in ('font_slot','batch_count','gui_slot','current_color')]
    spans=[]
    for n,node in enumerate(nodes):
        length=256 if n==0 else 72
        code=bytearray(b'\x90'*length)
        if n<11:
            signature=bytes.fromhex(profile['hooks'][n]['signature']);code[:len(signature)]=signature
        else:code[:3]=b'\x48\x89\xc8'
        code[24:29]=b'\xb8'+struct.pack('<I',n+1);code[-1]=0xc3
        refs=[]
        if n==0:
            position=32
            for target_node in range(1,count):
                code[position]=0xe8
                disp=rvas[target_node]-(rvas[n]+position+5)
                struct.pack_into('<i',code,position+1,disp)
                refs.append({'offset':position+1,'size':4,'instruction_end':position+5,
                             'role':target_node,'target':old_targets[target_node], 'flags':0x60000000,
                             'literal_length':0,'literal_sha256':'00'*32})
                position+=5
            for g in range(4):
                code[position:position+3]=b'\x48\x8b\x05'
                struct.pack_into('<i',code,position+3,globals_[g]-(rvas[n]+position+7))
                refs.append({'offset':position+3,'size':4,'instruction_end':position+7,
                             'role':count+g,'target':old_targets[count+g], 'flags':0xc0000000,
                             'literal_length':0,'literal_sha256':'00'*32})
                position+=7
        normalized=bytearray(code)
        for ref in refs:normalized[ref['offset']:ref['offset']+ref['size']]=b'\0'*ref['size']
        node.update(length=length,pdata=1,sha256=hashlib.sha256(normalized).hexdigest(),
                    anchor=bytes(normalized[:24]).hex(),references=refs)
        at=offset(rvas[n]);data[at:at+length]=code;spans.append((rvas[n],rvas[n]+length,0x5000))
    scopes=[]
    for n,scope in enumerate(model['scopes']):
        text=bytes.fromhex(scope['source_hex']);rva=0x5100+n*0x100
        at=offset(rva);data[at-16:at-8]=b'\xff'*8;struct.pack_into('<Q',data,at-8,len(text));data[at:at+len(text)]=text
        slot=0x9000+n*0x400
        struct.pack_into('<QQ',data,offset(slot),BASE+rva,n+1)
        scope['radius']=128 if scope['legacy_rva']==0x30dc50 else 512
        tokens=bytearray()
        for address in range(slot-scope['radius'],slot+scope['radius'],8):
            value=struct.unpack_from('<Q',data,offset(address))[0]
            if value==BASE+rva:tokens+=b'S'+struct.pack('<I',len(text))+hashlib.sha256(text).digest()
            else:tokens+=b'C'+struct.pack('<Q',value)
        scope['context_sha256']=hashlib.sha256(tokens).hexdigest();scopes.append((scope['legacy_rva'],rva))
    pdata=b''.join(struct.pack('<3I',*span) for span in spans);data[offset(0xe000):offset(0xe000)+len(pdata)]=pdata
    struct.pack_into('<II',data,opt+136,0xe000,len(pdata))
    layout=[globals_[0],*rvas[11:16],globals_[1],globals_[2],globals_[3]]
    expected={'hooks':rvas[:11],'layout':layout,'scopes':[list(p) for p in scopes]}
    return data,model,expected,sections,offset


def relocate(data,sections,delta):
    moved=bytearray(data);opt=0x98
    base=struct.unpack_from('<Q',moved,opt+24)[0];image_size=struct.unpack_from('<I',moved,opt+56)[0]
    for n,(_,rva,size,raw,flags) in enumerate(sections):
        struct.pack_into('<I',moved,opt+0xf0+n*40+12,rva+delta)
        if not flags&0x20000000:
            for pos in range(raw,raw+size-7,8):
                value=struct.unpack_from('<Q',moved,pos)[0]
                if base<=value<base+image_size:struct.pack_into('<Q',moved,pos,value+delta)
    struct.pack_into('<I',moved,opt+56,image_size+delta)
    pdata_size=struct.unpack_from('<I',moved,opt+140)[0]
    struct.pack_into('<I',moved,opt+136,0xe000+delta)
    for pos in range(0xc400,0xc400+pdata_size,4):
        value=struct.unpack_from('<I',moved,pos)[0]
        if value:struct.pack_into('<I',moved,pos,value+delta)
    return moved


def make_cases(enabled,expected):
    mapping=dict(expected['scopes'])
    fallback={r['en']:r['zh'] for r in enabled if not r.get('source_rva')}
    records=[]
    for row in enabled:
        old=row.get('source_rva',0);current=mapping[old] if old else 0
        records.append((current,row['en'],row['zh'],current,0))
        if old:
            records.append((0,row['en'],fallback.get(row['en'],''),0,1))
            records.append((old,row['en'],fallback.get(row['en'],''),0,2))
    records.append((0,'Future content that is absent from the localization dictionary.','',0,1))
    data=bytearray(b'ZPV1'+struct.pack('<I9I',len(records),*expected['layout']))
    for rva,en,zh,scope,kind in records:
        a=en.encode('latin-1');b=zh.encode('utf-8');data+=struct.pack('<5I',rva,len(a),len(b),scope,kind)+a+b
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-exe',type=Path,action='append',default=[])
    parser.add_argument('--detect-exe',type=Path,help='Read-only detection of a future EXE; no supported-version entry required.')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    zig=find_zig();env=compiler_environment()
    verifier=OUT/'compatibility_verify.exe'
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-municode','-O2','-Wall','-Wextra','-Werror',
                    str(ROOT/'native/compatibility_verify.c'),str(ROOT/'native/compatibility.c'),'-lbcrypt','-o',str(verifier)],env=env,check=True)
    if args.detect_exe:
        proc=subprocess.run([str(verifier),str(args.detect_exe),str(ROOT/'build/compatibility.zhc'),'--mapped-test'],
                            capture_output=True,text=True,encoding='utf-8',timeout=30)
        result=json.loads(proc.stdout)
        result['exe_sha256']=hashlib.sha256(args.detect_exe.read_bytes()).hexdigest()
        result['game_executed_or_modified']=False
        (OUT/'detection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2));return proc.returncode
    template=json.loads((ROOT/'data/compatibility.json').read_text(encoding='utf-8'))
    profiles=json.loads((ROOT/'data/versions.json').read_text(encoding='utf-8'))['versions']
    profile=next(p for p in profiles if p['exe_sha256']==template['baseline_exe_sha256'])
    data,model,expected,sections,offset=synthetic(template,profile)
    metadata=compile_data(model)
    actual_verifier=verifier
    test_contract='-DZH_COMPAT_TEST_CONTRACT="'+contract_hash(model)+'"'
    verifier=OUT/'owned_compatibility_verify.exe'
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-municode','-O2','-Wall','-Wextra','-Werror',test_contract,
                    str(ROOT/'native/compatibility_verify.c'),str(ROOT/'native/compatibility.c'),'-lbcrypt','-o',str(verifier)],env=env,check=True)
    owned_renderer=OUT/'owned_render_state_verify.exe'
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-Wall','-Wextra','-Werror',test_contract,
                    str(ROOT/'native/render_state_verify.c'),str(ROOT/'native/compatibility.c'),'-lbcrypt','-lopengl32','-o',str(owned_renderer)],env=env,check=True)
    cases=[]
    def run(name,exe,config,compatible,want=None,mapped=False,render=False):
        folder=OUT/name;folder.mkdir(exist_ok=True)
        exe_path=folder/'fixture.bin';config_path=folder/'compatibility.zhc'
        exe_path.write_bytes(exe);config_path.write_bytes(config)
        command=[str(verifier),str(exe_path),str(config_path)]+(['--mapped-test'] if mapped else [])
        proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
        result=json.loads(proc.stdout)
        assert proc.returncode==(0 if compatible else 1) and result['compatible']==compatible,(name,proc.returncode,result,proc.stderr)
        if want:
            assert all(result[k]==v for k,v in want.items()),(name,result,want)
        if render:
            from stage_preview import select
            fixture=folder/'dictionary-cases.bin';fixture.write_bytes(make_cases(select()[0],want))
            for relative in ('fonts/ui.zhf','translations/ui.utf8'):
                target=folder/'ExanimaZh'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/'build/preview-package/ExanimaZh'/relative,target)
            native=folder/'render_state_verify.exe';shutil.copy2(owned_renderer if verifier!=actual_verifier else ROOT/'build/render-state-test/render_state_verify.exe',native)
            draw=subprocess.run([str(native),'--auto-file',str(exe_path),'--metadata',str(config_path),'--cases',str(fixture)],
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert draw.returncode==0,(name,draw.returncode,draw.stdout,draw.stderr)
            result['render_test']=draw.stdout
            result['future_english_fallback']=True
        cases.append({'name':name,'expected_compatible':compatible,'mapped_memory_checks':mapped,**result})
    run('owned_fixture',data,metadata,True,expected,mapped=True,render=True)
    shifted=relocate(data,sections,0x10000)
    shifted_expected={k:([v+0x10000 for v in values] if k!='scopes' else [[a,b+0x10000] for a,b in values]) for k,values in expected.items()}
    run('all_addresses_shifted',shifted,metadata,True,shifted_expected,mapped=True,render=True)
    changed=bytearray(data);changed[offset(0x1100)+26]^=1
    run('function_body_changed',changed,metadata,False)
    changed=bytearray(data);ref=model['functions'][0]['references'][10]
    struct.pack_into('<i',changed,offset(0x1100)+ref['offset'],0x1100-(0x1100+ref['instruction_end']))
    run('call_target_changed',changed,metadata,False)
    changed=bytearray(data);ref=model['functions'][0]['references'][-1]
    struct.pack_into('<i',changed,offset(0x1100)+ref['offset'],0x7100-(0x1100+ref['instruction_end']))
    run('global_alias_changed',changed,metadata,False)
    changed=bytearray(data);changed[offset(0x5100)]^=1
    run('scoped_source_changed',changed,metadata,False)
    changed=bytearray(data);struct.pack_into('<Q',changed,offset(0x9000)+8,123)
    run('scoped_context_changed',changed,metadata,False)
    updated_context=copy.deepcopy(model)
    tokens=bytearray();source=bytes.fromhex(model['scopes'][0]['source_hex'])
    for address in range(0x9000-512,0x9000+512,8):
        value=struct.unpack_from('<Q',changed,offset(address))[0]
        if value==BASE+0x5100:tokens+=b'S'+struct.pack('<I',len(source))+hashlib.sha256(source).digest()
        else:tokens+=b'C'+struct.pack('<Q',value)
    updated_context['scopes'][0]['context_sha256']=hashlib.sha256(tokens).hexdigest()
    updated_context_bytes=compile_data(updated_context);updated_context_exe=bytes(changed)
    run('external_context_update_same_code_contract',changed,updated_context_bytes,True,expected,mapped=True,render=True)
    changed=bytearray(data);changed[offset(0xc000)-512:offset(0xc000)+512]=changed[offset(0x9000)-512:offset(0x9000)+512]
    run('ambiguous_scope_context',changed,metadata,False)
    def duplicate_function(data,index,new_rva):
        changed=bytearray(data);old=expected['hooks'][index] if index<11 else 0x1100+index*0x100
        length=model['functions'][index]['length'];changed[offset(new_rva):offset(new_rva)+length]=changed[offset(old):offset(old)+length]
        for ref in model['functions'][index]['references']:
            disp=struct.unpack_from('<i',changed,offset(new_rva)+ref['offset'])[0]
            struct.pack_into('<i',changed,offset(new_rva)+ref['offset'],disp+old-new_rva)
        size=struct.unpack_from('<I',changed,0x98+140)[0]
        struct.pack_into('<3I',changed,0xc400+size,new_rva,new_rva+length,0x5000)
        struct.pack_into('<I',changed,0x98+140,size+12)
        return changed
    run('ambiguous_hook',duplicate_function(data,0,0x4000),metadata,False)
    changed=duplicate_function(data,11,0x4000);ref=model['functions'][0]['references'][10]
    struct.pack_into('<i',changed,offset(0x1100)+ref['offset'],0x4000-(0x1100+ref['instruction_end']))
    helper_expected=copy.deepcopy(expected);helper_expected['layout'][1]=0x4000
    run('helper_relocated_call_graph',changed,metadata,True,helper_expected,mapped=True,render=True)
    changed=bytearray(data);new_text=0x5b00;text=bytes.fromhex(model['scopes'][1]['source_hex'])
    at=offset(new_text);changed[at-16:at-8]=b'\xff'*8;struct.pack_into('<Q',changed,at-8,len(text));changed[at:at+len(text)]=text
    struct.pack_into('<Q',changed,offset(0x9400),BASE+new_text)
    scope_expected=copy.deepcopy(expected);scope_expected['scopes'][1][1]=new_text
    run('duplicate_word_moved_by_context',changed,metadata,True,scope_expected,mapped=True,render=True)
    run('metadata_missing',data,b'',False)
    run('metadata_truncated',data,metadata[:90],False)
    corrupted=bytearray(metadata);corrupted[100]^=1
    run('metadata_checksum_changed',data,corrupted,False)
    malformed=copy.deepcopy(model);malformed['functions'][0]['references'][0]['role']=1000
    run('metadata_invalid_role',data,compile_data(malformed),False)
    malformed=copy.deepcopy(model);malformed['functions'][11]['rva']+=1
    run('metadata_wrong_helper_role',data,compile_data(malformed),False)
    malformed=copy.deepcopy(model);malformed['functions'][0]['references'][0]['role']=-1
    run('metadata_omitted_call_relation',data,compile_data(malformed),False)
    malformed=copy.deepcopy(model);malformed['functions'][0]['references'][-1]['target']+=1
    run('metadata_wrong_global_identity',data,compile_data(malformed),False)
    trailing=metadata[:-32]+b'unexpected';trailing+=hashlib.sha256(trailing).digest()
    run('metadata_trailing_data',data,trailing,False)
    malformed=copy.deepcopy(model);malformed['scopes'][0]['source_hex']='4258436b'
    run('metadata_source_contract_changed',data,compile_data(malformed),False)
    # A valid-checksum configuration cannot relax code matching in the production build.
    forged=copy.deepcopy(template);forged['functions'][0]['sha256']='00'*32
    original_verifier=verifier;verifier=actual_verifier
    run('production_code_contract_not_relaxable',data,compile_data(forged),False)
    verifier=original_verifier
    run('truncated_executable',data[:300],metadata,False)
    changed=bytearray(data);struct.pack_into('<H',changed,0x84,0x14c)
    run('wrong_architecture',changed,metadata,False)
    changed=bytearray(data);struct.pack_into('<I',changed,0x98+0xf0+40+12,0x2000)
    run('overlapping_sections',changed,metadata,False)
    # The host redirects only its own module/file identity and mapped image.
    # It calls the production initializer, parser, hook transaction and dictionary.
    runtime_host=OUT/'runtime_compat_verify.exe'
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-municode','-DZH_VERIFY','-O2','-Wall','-Wextra','-Werror',test_contract,
                    str(ROOT/'native/runtime_compat_verify.c'),str(ROOT/'native/unicode.c'),str(ROOT/'native/compatibility.c'),
                    '-lbcrypt','-lopengl32','-o',str(runtime_host)],env=env,check=True)
    initialization=[]
    for name,mode,payload,input_bytes in [('automatic_startup','accept',metadata,data),('bad_metadata_no_hooks','reject',bytes(corrupted),data),
                              ('changed_loaded_no_hooks','changed-loaded',metadata,data),
                              ('external_context_update','accept',updated_context_bytes,updated_context_exe)]:
        folder=OUT/name;folder.mkdir(exist_ok=True)
        shutil.copy2(runtime_host,folder/runtime_host.name)
        fixture=folder/'fixture.bin';fixture.write_bytes(input_bytes)
        assets=folder/'ExanimaZh';assets.mkdir(exist_ok=True)
        (assets/'compatibility.zhc').write_bytes(payload)
        for relative in ('fonts/ui.zhf','translations/ui.utf8'):
            target=assets/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/'build/preview-package/ExanimaZh'/relative,target)
        run_result=subprocess.run([str(folder/runtime_host.name),str(fixture),mode],capture_output=True,text=True,encoding='utf-8',timeout=30)
        result=json.loads(run_result.stdout)
        assert run_result.returncode==0 and result['passed'],(name,run_result.returncode,result,run_result.stderr)
        result['log']=(assets/'logs/latest.log').read_text(encoding='utf-8')
        initialization.append({'name':name,**result})
    for game in args.game_exe:
        verifier=actual_verifier
        raw=game.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        reviewed=next(p for p in profiles if p['exe_sha256']==sha)
        want={'hooks':[int(h['rva'],0) for h in reviewed['hooks']],
              'layout':[int(reviewed['layout'][n],0) for n in LAYOUT_NAMES],
              'scopes':[[int(s['legacy_rva'],0),int(s['current_rva'],0)] for s in reviewed['scopes']]}
        run('actual_'+reviewed['id'],raw,(ROOT/'build/compatibility.zhc').read_bytes(),True,want,mapped=True,render=True)
    report={'passed':True,'cases':cases,'case_count':len(cases),'initialization_cases':initialization,'game_files_executed_or_modified':False,
            'visual_confirmation_pending':True,'scope':'Real native detector plus loaded-byte mutation checks, actual Unicode layout/draw paths, pointer scopes and unknown-text English fallback.'}
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':raise SystemExit(main())
