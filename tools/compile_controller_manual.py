"""Reuse unchanged manual paragraphs and translate the controller-specific text."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
common=read('translations/manual_terms.json');extra=read('translations/manual_controller_terms.json')
sources=read('build/catalog/resource-sources.json');entries=[]
for row in sources:
    if row['source']!='manualcn.fds':continue
    chapter=row['id'].split(':')[1];en=row['en'].removesuffix('\0');zh=en
    replacements={**{r['en']:r['zh'] for r in common[chapter]},**extra}
    for a,b in sorted(replacements.items(),key=lambda x:len(x[0]),reverse=True):zh=zh.replace(a,b)
    plain=re.sub(r'\[[^]]*\]','',zh)
    assert not re.search(r'[A-Za-z]{3,} [A-Za-z]{3,}',plain),(chapter,plain)
    assert re.findall(r'\r\n|\r|\n|\[[^]]*\]',en)==re.findall(r'\r\n|\r|\n|\[[^]]*\]',zh),chapter
    entries.append({'id':'controller.'+chapter,'en':en,'zh':zh,'source':'manualcn.fds','source_ids':[row['id']],'status':'translated_not_visual_verified'})
(ROOT/'translations/manual-controller.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Controller manual chapters:',len(entries))
