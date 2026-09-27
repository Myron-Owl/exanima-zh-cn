"""Compile reviewed dialogue and bounded item rules for the render-time dictionary."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
def write(name,rows):
    (ROOT/'translations'/name).write_text(json.dumps({'language':'zh-CN','entries':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    source=read('build/catalog/dialogue-sources.json');by_id={str(r['offset']):r for r in source}
    mapping=read('translations/dialogue_by_offset.json')
    by_en={}
    for offset,zh in mapping.items():
        row=by_id[offset]
        assert row['kind']=='candidate'
        assert re.findall(r'\{[^}]+\}|\r\n|\r|\n',row['en'])==re.findall(r'\{[^}]+\}|\r\n|\r|\n',zh),offset
        assert row['en'] not in by_en or by_en[row['en']]==zh
        by_en[row['en']]=zh
    dialogue=[dict(r,zh=by_en[r['en']],status='translated_not_visual_verified') for r in source if r['en'] in by_en]
    write('dialogue.json',dialogue)
    generated={}
    def add(en,zh):
        if en in generated:assert generated[en]==zh,(en,generated[en],zh)
        generated[en]=zh
    for kind,terms in read('translations/item_grammar.json').items():
        for en,zh in terms.items():add('@item.'+kind+':'+en,zh)
    for en,zh in read('translations/message_templates.json').items():
        assert re.findall(r'\{[nrsmi][0-3]\}',en)==re.findall(r'\{[nrsmi][0-3]\}',zh)
        assert len(re.sub(r'\{[^}]*\}','',en))>=4 or en=='{s0} ({r1})'
        add('@format:'+en,zh)
    # The record builder at RVA 0x1970a0 uses match names, lowercased by
    # 0x17b10, not character ranks. Keep this namespace finite and separate.
    match_types={'duel':'决斗','doubles':'双人','skirmish':'小队战','fray':'混战',
                 'reserve':'替补战','pugilism':'拳斗','challenger':'挑战者','elimination':'淘汰',
                 'valiance':'勇战','valour':'英勇','captain':'队长','brawl':'斗殴','beast':'巨兽'}
    for en,zh in match_types.items():add('@match.type:'+en,zh)
    item_names=read('translations/item_names.json')
    for en,zh in item_names.items():add('@item.name:'+en.lower(),zh)
    for row in read('translations/item-descriptions.json')['entries']:
        en,zh=row['en'],row['zh']
        if '@WEAR' in en:
            english=re.split(r'@WEAR\d+:',en);chinese=re.split(r'@WEAR\d+:',zh)
            assert len(english)==len(chinese)
            for a,b in zip(english[1:],chinese[1:]):
                # Bottle labels precede all wear branches and must not be discarded.
                add(english[0]+a,chinese[0]+b)
                add((english[0]+a).rstrip(),(chinese[0]+b).rstrip())
            continue
        if not ('\x10' in en or re.search(r'\[(sq|pq|sc)\]',en) or re.match(r'[-a-z]',en)):continue
        # Preserve material and body-part information; only engine grammar tokens are removed.
        a=re.sub(r'\[(sq|pq|sc)\]','',en).replace('\x10 ','').lstrip('-').strip()
        b=re.sub(r'\[(sq|pq|sc)\]','',zh).replace('\x10','').lstrip('-').strip()
        a=re.sub(r'^(?:A |An )','',a).rstrip('.')
        b=b.rstrip('。.')
        if not a or not b:continue
        # Token-free and token-bearing versions can have equivalent wording.
        generated.setdefault('@item.base:'+a,b)
    rows=[{'id':'generated.runtime.'+str(i),'en':en,'zh':zh,'source':'generated_runtime_rule','status':'translated_not_visual_verified'} for i,(en,zh) in enumerate(sorted(generated.items()))]
    write('runtime_generated.json',rows)
    print(json.dumps({'dialogue_source_records':len(dialogue),'dialogue_unique':len(by_en),'runtime_rules':len(rows),'item_bases':sum(r['en'].startswith('@item.base:') for r in rows)}))
if __name__=='__main__':main()
