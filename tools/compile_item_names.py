"""Join reviewed item names with original source IDs; don't alter template tokens."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'build/catalog/sources.json').read_text(encoding='utf-8'))
names=json.loads((ROOT/'translations/item_names.json').read_text(encoding='utf-8'))
items=[r for r in rows if r['source']=='objstrings.rdb']
assert set(names)<={r['en'] for r in items},set(names)-{r['en'] for r in items}
entries=[]
for en,zh in names.items():
    refs=[r['id'] for r in items if r['en']==en]
    entries.append({'id':'item.'+refs[0].split(':')[1],'en':en,'zh':zh,'source':'objstrings.rdb','source_ids':refs,'status':'translated_not_visual_verified'})
(ROOT/'translations/items.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'unique_item_names':len(entries),'source_records':sum(len(r['source_ids']) for r in entries),'item_source_total':len(items)},indent=2))
