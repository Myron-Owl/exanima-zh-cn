"""Compile portable reviewed fingerprints; never read or distribute a game EXE."""
import argparse,hashlib,json,struct
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def contract_hash(data):
    prefix=52+sum(80+60*len(n['references']) for n in data['functions'])
    return hashlib.sha256(compile_data(data)[:prefix]).hexdigest()

def contract_header(data):
    digest=bytes.fromhex(contract_hash(data))
    rows=['/* Generated immutable code/ABI contract; scope contexts remain external. */',
          '#ifndef EXANIMA_ZH_COMPATIBILITY_CONTRACT_H','#define EXANIMA_ZH_COMPATIBILITY_CONTRACT_H',
          'static const unsigned char zh_compat_contract_digest[32]={'+','.join(f'0x{x:02x}' for x in digest)+'};',
          'typedef struct { uint32_t legacy,length; unsigned char hash[32]; } ZhCompatScopeContract;',
          'static const ZhCompatScopeContract zh_compat_scope_contracts[9]={']
    for scope in data['scopes']:
        text=bytes.fromhex(scope['source_hex']);sha=hashlib.sha256(text).digest()
        rows.append('    {'+str(scope['legacy_rva'])+','+str(len(text))+',{'+','.join(f'0x{x:02x}' for x in sha)+'}},')
    rows+=['};','#endif','']
    return '\n'.join(rows).encode('utf-8')

def compile_data(data):
    assert data['schema_version']==1
    nodes=data['functions'];scopes=data['scopes']
    assert 16<=len(nodes)<=32 and len(scopes)==9
    blob=bytearray(b'ZHCMP001'+struct.pack('<3I',1,len(nodes),len(scopes))+bytes.fromhex(data['baseline_exe_sha256']))
    for index,node in enumerate(nodes):
        anchor=bytes.fromhex(node['anchor']);refs=node['references']
        assert len(anchor)==min(24,node['length']) and 1<=node['length']<=65536 and len(refs)<=512
        assert node['copy_size']==0 or (index<11 and 14<=node['copy_size']<=24)
        blob+=struct.pack('<6I',node['rva'],node['length'],node['pdata'],node['copy_size'],len(anchor),len(refs))
        blob+=bytes.fromhex(node['sha256'])+anchor.ljust(24,b'\0')
        for ref in refs:
            assert ref['size'] in (1,4) and 0<=ref['offset']<=node['length']-ref['size']
            assert ref['offset']+ref['size']<=ref['instruction_end']<=node['length']
            blob+=struct.pack('<3Ii3I',ref['offset'],ref['size'],ref['instruction_end'],ref['role'],ref['target'],ref['flags'],ref['literal_length'])
            blob+=bytes.fromhex(ref['literal_sha256'])
    for scope in scopes:
        source=bytes.fromhex(scope['source_hex'])
        assert 0<len(source)<=20000 and scope['radius'] in (0,128,512)
        blob+=struct.pack('<3I',scope['legacy_rva'],len(source),scope['radius'])+bytes.fromhex(scope['context_sha256'])+source
    blob+=hashlib.sha256(blob).digest()
    assert len(blob)<2*1024*1024
    return bytes(blob)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'data/compatibility.json')
    parser.add_argument('--output',type=Path,default=ROOT/'build/compatibility.zhc')
    parser.add_argument('--check',action='store_true',help='Check immutable header without creating any build output.')
    args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8'))
    if args.check:
        header=ROOT/'native/compatibility_contract.h'
        if not header.exists() or header.read_bytes()!=contract_header(data):
            raise SystemExit('Compatibility contract header is stale; run tools/compile_compatibility.py')
        print('Immutable compatibility contract header matches the reviewed source.');return
    out=args.output;out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(compile_data(data))
    if args.input.resolve()==(ROOT/'data/compatibility.json').resolve():
        (ROOT/'native/compatibility_contract.h').write_bytes(contract_header(data))
    print(json.dumps({'compatibility_file':str(out),'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))

if __name__=='__main__':main()
