"""Build a reviewed, standalone batch without touching original game archives."""
from pathlib import Path
import collections,hashlib,json,re,shutil,struct
ROOT=Path(__file__).resolve().parents[1]
INPUTS=['ui.json','ui-expanded.json','ui-supplement.json','runtime_ui.json','runtime_generated.json','dialogue.json','maps.json','skills.json','items.json','arena.json','content.json','item-descriptions.json','powers.json','narrator.json','manual.json','manual-controller.json']

# source_ids beginning with ``exe:`` are offsets in the 0.9.5.2 executable
# file, while the native matcher needs loaded-image RVAs. Keep the target
# version's PE section map here so a raw offset can never silently be emitted.
EXE_FILE_SECTIONS=(
    (0x00000400,0x002a5200,0x00001000), # .text
    (0x002a5600,0x0004a400,0x002a7000), # .data
    (0x002efa00,0x00081000,0x002f2000), # .rdata
    (0x00370a00,0x00015800,0x00373000), # .pdata
    (0x00386200,0x00000200,0x005ba000), # .CRT
    (0x00386400,0x00001e00,0x005bb000), # .idata
    (0x00388200,0x00000200,0x005bd000), # .edata
    (0x00388400,0x00040000,0x005be000), # .rsrc
)

def exe_file_offset_to_rva(offset):
    for raw_start,raw_size,rva_start in EXE_FILE_SECTIONS:
        if raw_start<=offset<raw_start+raw_size:
            return rva_start+(offset-raw_start)
    raise ValueError(f'EXE file offset outside mapped sections: 0x{offset:x}')

def select():
    grouped=collections.defaultdict(list)
    sources=json.loads((ROOT/'build/catalog/sources.json').read_text(encoding='utf-8'))
    sources+=json.loads((ROOT/'build/catalog/resource-sources.json').read_text(encoding='utf-8'))
    sources+=json.loads((ROOT/'build/catalog/dialogue-sources.json').read_text(encoding='utf-8'))
    sources+=json.loads((ROOT/'build/catalog/map-sources.json').read_text(encoding='utf-8'))
    known={r['en'] for r in sources}
    known.update(r['en'].removesuffix('\0') for r in sources if r.get('source') in ('manualkm.fds','manualcn.fds'))
    for filename in INPUTS:
        for row in json.loads((ROOT/'translations'/filename).read_text(encoding='utf-8'))['entries']:
            assert row['en'] in known or row.get('source') in ('runtime_capture','generated_runtime_rule'),(filename,row['id'])
            assert re.findall(r'\[[^\]]*\]|@WEAR\d+:|\x10',row['en'])==re.findall(r'\[[^\]]*\]|@WEAR\d+:|\x10',row['zh']),(filename,row['id'],'control mismatch')
            grouped[row['en']].append(dict(row,translation_file=filename))
    enabled=[];deferred=[]
    for source,rows in sorted(grouped.items()):
        if source=='UNKNOWN':
            # Decorative character-background heading uses the same title path
            # as the main menu and must remain in the original artwork style.
            deferred.append({'en':source,'reason':'decorative_title_preserved','entries':rows})
            continue
        targets={r['zh'] for r in rows}
        reason=None
        if len(targets)>1:
            # A static EXE label can coexist with one resource-loaded meaning.
            # Exact RVA matches take precedence over the unscoped resource fallback.
            scoped=[];fallback=[]
            for candidate in rows:
                ids=candidate.get('source_ids') or []
                exe_ids=[value for value in ids if value.startswith('exe:')]
                if ids and len(exe_ids)==len(ids):
                    scoped.extend(dict(candidate,source_rva=exe_file_offset_to_rva(int(value.split(':',1)[1],16))) for value in exe_ids)
                else:fallback.append(candidate)
            if scoped and len({r['zh'] for r in fallback})==1:
                enabled.extend(scoped+[fallback[0]])
                continue
            reason='context_conflict'
        elif '{\xaeExanima.' in source: reason='expanded_map_variable_template'
        elif '\x10' in source or '@WEAR' in source or re.search(r'\[(?:sq|pq|sc)\]',source): reason='dynamic_item_template'
        elif source.startswith('-'): reason='item_grammar_fragment'
        if reason: deferred.append({'en':source,'reason':reason,'entries':rows});continue
        row=rows[0]
        if source=='Back':
            # Only the movement binding's verified static string; the file browser has a different Back.
            row=dict(row,source_rva=0x305150)
        assert row['zh'] and all(ord(c)>=32 or c in '\r\n\t' for c in row['zh'])
        enabled.append(dict(row,ids=[r['id'] for r in rows]))
    return enabled,deferred,sources

def escape(text,source=False):
    text=text.replace('\\','\\\\').replace('\r','\\r').replace('\n','\\n').replace('\t','\\t')
    # English keys represent engine bytes stored losslessly as Latin-1. Writing
    # accented keys as UTF-8 would change ç from E7 to C3 A7 and prevent matching.
    if source:
        text.encode('latin-1')  # Reject accidentally Unicode-decoded source keys.
    return re.sub(r'[\x80-\xff]' if source else r'[\x80-\x9f]',lambda m:f'\\x{ord(m[0]):02x}',text)

def main():
    enabled,deferred,sources=select()
    out=ROOT/'build/preview-package'
    for sub in ('ExanimaZh/fonts','ExanimaZh/translations','ExanimaZh/licenses'):(out/sub).mkdir(parents=True,exist_ok=True)
    for name in ('winmm.dll','ExanimaZh.dll'):shutil.copy2(ROOT/'build/native'/name,out/name)
    font=ROOT/'build/fonts/32px';meta=json.loads((font/'metrics.json').read_text())
    glyphs={g['codepoint'] for g in meta['glyphs']}
    for r in enabled:assert set(map(ord,r['zh']))-set(map(ord,'\r\n\t'))<=glyphs,r['id']
    blob=bytearray(struct.pack('<4s5I',b'ZHF1',meta['pixel_size'],meta['page_size'],meta['page_count'],len(meta['glyphs']),0))
    for g in meta['glyphs']:blob+=struct.pack('<6I3i',*(g[k] for k in ('codepoint','page','x','y','width','height','bearing_x','bearing_y','advance_64')))
    for i in range(meta['page_count']):blob+=(font/f'page-{i:03}.a8').read_bytes()[12:]
    (out/'ExanimaZh/fonts/ui.zhf').write_bytes(blob)
    (out/'ExanimaZh/translations/ui.utf8').write_text(''.join(escape(r['en'],source=True)+'\t'+escape(r['zh'])+('\t'+format(r['source_rva'],'x') if r.get('source_rva') else '')+'\n' for r in enabled),encoding='utf-8',newline='\n')
    exact={r['en'] for r in enabled}
    map_rows=json.loads((ROOT/'build/catalog/map-sources.json').read_text(encoding='utf-8'))
    dialogue_rows=json.loads((ROOT/'translations/dialogue.json').read_text(encoding='utf-8'))['entries']
    internal_rules=sum(r['en'].startswith(('@item.','@format:','@match.type:')) for r in enabled)
    report={'enabled_unique_strings':len(enabled),'deferred_unique_strings':len(deferred),
            'visible_text_records':len(enabled)-internal_rules,'internal_matching_rules':internal_rules,
            'dialogue_unique_written':len({r['en'] for r in dialogue_rows}),
            'map_unique_written':len({r['en'] for r in map_rows}),
            'map_referenced_records':len(map_rows),
            'dynamic_item_bases':sum(r['en'].startswith('@item.base:') for r in enabled),
            'dynamic_message_templates':sum(r['en'].startswith('@format:') for r in enabled),
            'templates_handled_by_generated_rules':sum(r['reason'] in ('dynamic_item_template','item_grammar_fragment','expanded_map_variable_template') for r in deferred),
            'unresolved_translation_conflicts':sum(r['reason']=='context_conflict' for r in deferred),
            'enabled_by_translation_file':dict(collections.Counter(r['translation_file'] for r in enabled)),
            'source_records_with_exact_translation':dict(collections.Counter(r['source'] for r in sources if r['en'] in exact)),
            'long_text_or_format_entries':sum(len(r['en'])>80 or any(c in r['en'] for c in '\r\n[') for r in enabled),
            'settings_page_user_verified':True,'expanded_game_visual_verified':False,'full_localization':False,
            'runtime_revision':f'{len(enabled)}-audit-preview',
            'previous_revision_user_verified_pages':['settings','controls','powers'],
            'parchment_fix_game_visual_verified':True,
            'manual_movement_game_visual_verified':False,
            'manual_all_chapters_translated':True,
            'manual_controller_chapters_translated':True,
            'manual_all_chapters_game_visual_verified':False,
            'deferred':deferred}
    (ROOT/'build/preview-coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'ExanimaZh/version.json').write_text(json.dumps({'game_version':'0.9.5.2','profile':'preview',**{k:v for k,v in report.items() if k!='deferred'}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ('OFL.txt','Latin-OFL.txt','provenance.json'):shutil.copy2(ROOT/'assets/fonts'/name,out/'ExanimaZh/licenses'/name)
    # Preserve the author's release text, including its encoding and line breaks.
    shutil.copyfile(ROOT/'release/README.txt',out/'ExanimaZh/README.txt')
    names=['winmm.dll','ExanimaZh.dll','ExanimaZh/fonts/ui.zhf','ExanimaZh/translations/ui.utf8','ExanimaZh/version.json','ExanimaZh/README.txt','ExanimaZh/licenses/OFL.txt','ExanimaZh/licenses/Latin-OFL.txt','ExanimaZh/licenses/provenance.json']
    manifest={n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in names}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='deferred'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
