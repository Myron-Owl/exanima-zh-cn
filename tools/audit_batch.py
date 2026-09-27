"""Content completeness is measured separately from runtime enablement and visual checks."""
from pathlib import Path
import collections,json,re
from stage_preview import ROOT,INPUTS,select,exe_file_offset_to_rva

def unique_object(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('Duplicate JSON key: '+key)
        out[key]=value
    return out

for path in (ROOT/'translations').glob('*.json'):
    json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique_object)
runtime_source=(ROOT/'native/runtime.c').read_text(encoding='utf-8')
assert '[tcol=FFFFFF00]' not in runtime_source
assert 'media_only_source' not in runtime_source
sources=json.loads((ROOT/'build/catalog/sources.json').read_text(encoding='utf-8'))
rows=[r for file in INPUTS for r in json.loads((ROOT/'translations'/file).read_text(encoding='utf-8'))['entries']]
for row in rows:
    en,zh=row['en'],row['zh']
    assert re.findall(r'\r\n|\r|\n',en)==re.findall(r'\r\n|\r|\n',zh),(row['id'],'paragraph breaks')
    assert re.findall(r'\[[^\]]*\]|@WEAR\d+:|\x10|\{[^}]+\}',en)==re.findall(r'\[[^\]]*\]|@WEAR\d+:|\x10|\{[^}]+\}',zh),(row['id'],'control tokens')
items=[r for r in sources if r['source']=='objstrings.rdb' and r['en'].strip()]
translated_items={r['en'] for r in rows if r.get('source')=='objstrings.rdb'}
missing=[r['id'] for r in items if r['en'] not in translated_items]
assert not missing,missing
enabled,deferred,_=select()
conflicts=[r['en'] for r in deferred if r['reason']=='context_conflict']
assert not conflicts,('Unresolved translation conflicts',conflicts)
map_sources=json.loads((ROOT/'build/catalog/map-sources.json').read_text(encoding='utf-8'))
maps={r['en'] for r in json.loads((ROOT/'translations/maps.json').read_text(encoding='utf-8'))['entries']}
assert all(r['en'] in maps for r in map_sources)
dialogue_sources=json.loads((ROOT/'build/catalog/dialogue-sources.json').read_text(encoding='utf-8'))
dialogue={r['en'] for r in json.loads((ROOT/'translations/dialogue.json').read_text(encoding='utf-8'))['entries']}
internal_dialogue={'Ac','Vi','Idle','Targ','Ex','De','{Actor[0].ContextPhrase}'}
dialogue_missing=[r for r in dialogue_sources if r['kind']=='candidate' and r['en'] not in dialogue and r['en'] not in internal_dialogue]
assert not dialogue_missing,dialogue_missing
metrics=json.loads((ROOT/'build/fonts/32px/metrics.json').read_text())
glyphs={g['codepoint'] for g in metrics['glyphs']}
assert all(set(map(ord,r['zh']))-set(map(ord,'\r\n\t'))<=glyphs for r in enabled)
assert next(r for r in enabled if r['en']=='Back')['source_rva']==0x305150
assert {'Weight','Counter','Crush','Ward'}<={r['en'] for r in enabled}
assert next(r for r in enabled if r['en']=='Shield')['zh']=='盾'
for term in ('Weight','Counter','Crush','Ward'):
    assert any(r.get('source_rva') for r in enabled if r['en']==term)
assert exe_file_offset_to_rva(0x30b650)==0x30dc50
assert {'SETTINGS','BACK','BEGIN','Blast','Release a blast pushing away anything in front of you.'}<={r['en'] for r in enabled}
assert {'Force','Energy','Light','Displacement','Forget all knowledge of this technique?','YES','NO',
        'COMPANY NAME','COMPANY EMBLEM','Randomise'}<={r['en'] for r in enabled}
assert 'UNKNOWN' not in {r['en'] for r in enabled}
assert next(r for r in enabled if r['en'].startswith("You don't know who you are"))['source_rva']==0x3102c8
report={'json_duplicate_keys':False,'paragraph_breaks_and_control_tokens_preserved':True,
        'item_nonblank_source_records':len(items),'item_unique_nonblank_sources':len({r['en'] for r in items}),
        'item_sources_without_written_translation':missing,'enabled_unique_translations':len(enabled),
        'map_referenced_source_records':len(map_sources),'map_unique_sources':len({r['en'] for r in map_sources}),
        'map_sources_without_written_translation':[],
        'dialogue_unique_sources_with_translation':len(dialogue),'dialogue_sources_without_written_translation':[],
        'dialogue_excluded_internal_values':sorted(internal_dialogue),
        'deferred_by_reason':dict(collections.Counter(r['reason'] for r in deferred)),
        'new_visual_verification':False,'full_localization':False}
(ROOT/'build/batch-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
