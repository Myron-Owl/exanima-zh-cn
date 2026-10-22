"""Generate relocation-aware fingerprints from an explicitly reviewed Steam EXE.

Maintainer-only analysis: normal builds compile the supplied JSON and need no EXE.
No complete game code is exported: only hashes, short anchors and reference metadata.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]


def context_hash(pe,slot,radius):
    data=bytearray()
    base=pe.OPTIONAL_HEADER.ImageBase
    for address in range(slot-radius,slot+radius,8):
        raw=pe.get_data(address,8)
        assert len(raw)==8
        value=struct.unpack('<Q',raw)[0]
        if base<=value<base+pe.OPTIONAL_HEADER.SizeOfImage:
            target=value-base
            section=pe.get_section_by_rva(target)
            prefix=pe.get_data(target-16,16) if target>=16 and section is not None else b''
            length=struct.unpack('<Q',prefix[8:])[0] if len(prefix)==16 else 0
            if prefix[:8]==b'\xff'*8 and 0<length<=20000 and len(pe.get_data(target,length))==length:
                data+=b'S'+struct.pack('<I',length)+hashlib.sha256(pe.get_data(target,length)).digest()
            else:
                data+=b'P'+(section.Name[:8].ljust(8,b'\0') if section else b'headers\0')+struct.pack('<I',section.Characteristics&0xe0000000 if section else 0)
        else:
            data+=b'C'+raw
    return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--analysis-libs',type=Path,required=True)
    parser.add_argument('--baseline-model',type=Path,help='Retain a shipped ABI baseline; update scoped contexts only after complete code/reference equivalence.')
    parser.add_argument('--output',type=Path,default=ROOT/'data/compatibility.json')
    args=parser.parse_args()
    sys.path.insert(0,str(args.analysis_libs))
    import pefile
    import capstone as cs
    from capstone.x86 import X86_OP_MEM,X86_OP_IMM,X86_REG_RIP
    raw=args.exe.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    profiles=json.loads((ROOT/'data/versions.json').read_text(encoding='utf-8'))['versions']
    profile=next(p for p in profiles if p['exe_sha256']==digest and 'steam_build_id' in p)
    pe=pefile.PE(data=raw)
    md=cs.Cs(cs.CS_ARCH_X86,cs.CS_MODE_64);md.detail=True
    pdata={e.struct.BeginAddress:e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
    def body(start):
        if start in pdata:
            end=pdata[start];boundary=1
        else:
            seen=[];furthest=start
            for ins in md.disasm(pe.get_data(start,4096),start):
                seen.append(ins)
                if ins.group(cs.CS_GRP_JUMP):
                    for op in ins.operands:
                        if op.type==X86_OP_IMM and start<=op.imm<start+4096:
                            furthest=max(furthest,op.imm)
                if ins.mnemonic=='ret' and ins.address>=furthest:break
            assert seen and seen[-1].mnemonic=='ret'
            end=seen[-1].address+seen[-1].size;boundary=0
            assert all(op.type!=X86_OP_IMM or start<=op.imm<end for ins in seen if ins.group(cs.CS_GRP_JUMP) for op in ins.operands)
        code=bytearray(pe.get_data(start,end-start))
        refs=[]
        instructions=list(md.disasm(code,start))
        assert instructions[-1].address+instructions[-1].size==end
        for ins in instructions:
            for op in ins.operands:
                at=size=target=0
                if op.type==X86_OP_MEM and op.mem.base==X86_REG_RIP:
                    at=ins.disp_offset;size=ins.disp_size;target=ins.address+ins.size+op.mem.disp
                elif op.type==X86_OP_IMM and (ins.group(cs.CS_GRP_CALL) or ins.group(cs.CS_GRP_JUMP)) and not start<=op.imm<end:
                    at=ins.imm_offset;size=ins.imm_size;target=op.imm
                if size:
                    assert size in (1,4)
                    offset=ins.address-start+at
                    code[offset:offset+size]=b'\0'*size
                    section=pe.get_section_by_rva(target);assert section
                    prefix=pe.get_data(target-16,16) if target>=16 else b''
                    length=struct.unpack('<Q',prefix[8:])[0] if len(prefix)==16 else 0
                    literal=pe.get_data(target,length) if prefix[:8]==b'\xff'*8 and 0<length<=20000 else b''
                    refs.append({'offset':offset,'size':size,'instruction_end':ins.address+ins.size-start,
                        'target':target,'flags':section.Characteristics&0xe0000000,
                        'literal_length':len(literal),'literal_sha256':hashlib.sha256(literal).hexdigest() if literal else '00'*32,
                        'branch':op.type==X86_OP_IMM})
        return {'rva':start,'length':end-start,'pdata':boundary,'sha256':hashlib.sha256(code).hexdigest(),
                'anchor':bytes(code[:24]).hex(),'references':refs}
    nodes=[dict(body(int(h['rva'],0)),name=h['name'],copy_size=len(bytes.fromhex(h['signature']))) for h in profile['hooks']]
    nodes += [dict(body(int(profile['layout'][name],0)),name=name,copy_size=0) for name in ('begin','end','uv','vertex','color')]
    seen={n['rva'] for n in nodes}
    dependencies=sorted({r['target'] for n in nodes for r in n['references'] if r['branch'] and r['target'] not in seen})
    for target in dependencies:
        nodes.append(dict(body(target),name=f'callee_{target:x}',copy_size=0))
    assert 16<=len(nodes)<=32
    roles={n['rva']:i for i,n in enumerate(nodes)}
    global_names=('font_slot','batch_count','gui_slot','current_color')
    roles.update({int(profile['layout'][name],0):len(nodes)+i for i,name in enumerate(global_names)})
    for node in nodes:
        for ref in node['references']:
            ref['role']=roles.get(ref['target'],-1)
    scopes=[]
    for scope in profile['scopes']:
        current=int(scope['current_rva'],0)
        target=struct.pack('<Q',pe.OPTIONAL_HEADER.ImageBase+current)
        slots=[];pos=0
        while (pos:=raw.find(target,pos))>=0:
            slots.append(pe.get_rva_from_offset(pos));pos+=1
        assert len(slots)<=1
        radius=128 if int(scope['legacy_rva'],0)==0x30dc50 else 512
        scopes.append({'legacy_rva':int(scope['legacy_rva'],0),'source_hex':scope['source_hex'],
                       'radius':radius if slots else 0,'context_sha256':context_hash(pe,slots[0],radius) if slots else '00'*32})
    result={'schema_version':1,'baseline_profile':profile['id'],'baseline_exe_sha256':digest,
            'functions':nodes,'scopes':scopes,
            'policy':'All full function hashes, call/data reference identities, typed scope contexts and loaded bytes must match. No first-hit fallback.'}
    if args.baseline_model:
        reference=json.loads(args.baseline_model.read_text(encoding='utf-8'))
        old_nodes=reference['functions']
        assert len(old_nodes)==len(nodes),'Dependency graph changed; runtime review/rebuild required'
        ordered=nodes[:16]
        for previous in old_nodes[16:]:
            matches=[n for n in nodes[16:] if (n['sha256'],n['length'])==(previous['sha256'],previous['length'])]
            assert len(matches)==1,'Callee changed or ambiguous; runtime review/rebuild required'
            ordered.append(matches[0])
        new_roles={n['rva']:i for i,n in enumerate(ordered)}
        new_roles.update({int(profile['layout'][name],0):len(nodes)+i for i,name in enumerate(global_names)})
        identities={}
        for before,after in zip(old_nodes,ordered):
            assert all(before[k]==after[k] for k in ('length','pdata','copy_size','sha256','anchor')),'Rendering code changed; runtime review/rebuild required'
            assert len(before['references'])==len(after['references'])
            for old_ref,new_ref in zip(before['references'],after['references']):
                assert all(old_ref[k]==new_ref[k] for k in ('offset','size','instruction_end','flags','literal_length','literal_sha256'))
                assert old_ref['role']==new_roles.get(new_ref['target'],-1),'Call/data role changed; runtime review/rebuild required'
                if old_ref['target'] in identities:assert identities[old_ref['target']]==new_ref['target']
                else:identities[old_ref['target']]=new_ref['target']
        assert len(set(identities.values()))==len(identities),'Reference identities collapsed'
        assert all((a['legacy_rva'],a['source_hex'],a['radius'])==(b['legacy_rva'],b['source_hex'],b['radius']) for a,b in zip(reference['scopes'],scopes))
        result=copy.deepcopy(reference)
        result['scopes']=scopes
        result['reviewed_for_exe_sha256']=digest
    dest=args.output
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'baseline':result['baseline_profile'],'reviewed_target':profile['id'],'functions':len(nodes),'references':sum(len(n['references']) for n in nodes),'scopes':len(scopes),'output':str(dest)}))


if __name__=='__main__':main()
