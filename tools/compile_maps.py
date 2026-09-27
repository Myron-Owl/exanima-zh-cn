"""Compile reviewed referenced map text and finite gender-token expansions."""
import json,re,itertools
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
source=read('build/catalog/map-sources.json');mapping=read('translations/maps_by_id.json')
by_en={r['en']:mapping[r['id']] for r in source if r['id'] in mapping}
assert len(by_en)==len({r['en'] for r in source})
entries=[]
for row in source:
    zh=by_en[row['en']]
    assert re.findall(r'\r\n|\r|\n|\[[^\]]*\]|\{[^}]*\}',row['en'])==re.findall(r'\r\n|\r|\n|\[[^\]]*\]|\{[^}]*\}',zh),row['id']
    entries.append(dict(row,zh=zh,status='translated_not_visual_verified'))
    tokens=re.findall(r'\{[^}]+\}',row['en'])
    if tokens:
        # The engine resolves these gender variables before handing text to the renderer.
        options={'HeShe':[('He','他'),('She','她'),('he','他'),('she','她')],
                 'HimHer':[('him','他'),('her','她')],
                 'HisHers':[('his','他的心智'),('hers','她的心智'),('her','她的心智')]}
        for i,variants in enumerate(itertools.product(*(options[t.split('.')[-1][:-1]] for t in tokens))):
            en=row['en'];target=zh
            for token,(a,b) in zip(tokens,variants):en=en.replace(token,a);target=target.replace(token,b)
            entries.append({'id':row['id']+':expanded:'+str(i),'en':en,'zh':target,'source':'generated_runtime_rule','status':'translated_not_visual_verified'})
(ROOT/'translations/maps.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'referenced_records':len(source),'unique_translations':len(by_en),'compiled_records':len(entries)}))
