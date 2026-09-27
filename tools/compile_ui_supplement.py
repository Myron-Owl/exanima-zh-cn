"""Compile remaining reviewed player-facing EXE labels."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sources=json.loads((ROOT/'build/catalog/sources.json').read_text(encoding='utf-8'))
terms=json.loads((ROOT/'translations/ui_supplement_terms.json').read_text(encoding='utf-8'))
rows=[]
for en,zh in terms.items():
    ids=[r['id'] for r in sources if r['source']=='Exanima.exe' and r['en']==en]
    assert ids,en
    rows.append({'id':'supplement.'+str(len(rows)),'en':en,'zh':zh,'source':'Exanima.exe','source_ids':ids,'status':'translated_not_visual_verified'})
(ROOT/'translations/ui-supplement.json').write_text(json.dumps({'language':'zh-CN','entries':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Supplemental UI translations:',len(rows))
