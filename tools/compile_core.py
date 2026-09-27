from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
sources=json.loads((ROOT/'build/catalog/sources.json').read_text(encoding='utf-8'))
for filename,output in [('ui_core.json','ui-expanded.json'),('skills_terms.json','skills.json'),('arena_terms.json','arena.json')]:
    mapping=json.loads((ROOT/'translations'/filename).read_text(encoding='utf-8'))
    entries=[]
    for i,(en,zh) in enumerate(mapping.items()):
        matches=[r['id'] for r in sources if r['source']=='Exanima.exe' and r['en']==en]
        assert matches,(filename,en)
        entries.append({'id':output.split('.')[0]+'.'+str(i),'en':en,'zh':zh,'source':'Exanima.exe',
                        'source_ids':matches,'status':'translated_not_visual_verified'})
    (ROOT/'translations'/output).write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(output,len(entries))
by_id={r['id']:r for r in sources}
mapping=json.loads((ROOT/'translations/content_by_id.json').read_text(encoding='utf-8'))
entries=[dict(by_id[key],zh=value,status='translated_not_visual_verified') for key,value in mapping.items()]
(ROOT/'translations/content.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('content.json',len(entries))
mapping=json.loads((ROOT/'translations/item_descriptions_by_id.json').read_text(encoding='utf-8'))
entries=[dict(by_id['objstrings.rdb:'+key],zh=value,status='translated_not_visual_verified') for key,value in mapping.items()]
(ROOT/'translations/item-descriptions.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('item-descriptions.json',len(entries))
resources=json.loads((ROOT/'build/catalog/resource-sources.json').read_text(encoding='utf-8'))
mapping=json.loads((ROOT/'translations/powers_terms.json').read_text(encoding='utf-8'))
entries=[]
for i,(en,zh) in enumerate(mapping.items()):
    matches=[r['id'] for r in resources if r['source'].endswith('.pwr') and r['en']==en]
    assert matches,en
    entries.append({'id':'powers.'+str(i),'en':en,'zh':zh,'source_ids':matches,'source':'powers','status':'translated_not_visual_verified'})
(ROOT/'translations/powers.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('powers.json',len(entries))
by_id={r['id']:r for r in resources}
mapping=json.loads((ROOT/'translations/narrator_by_id.json').read_text(encoding='utf-8'))
entries=[dict(by_id[key],zh=value,status='translated_not_visual_verified') for key,value in mapping.items()]
(ROOT/'translations/narrator.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('narrator.json',len(entries))

manual_mapping=json.loads((ROOT/'translations/manual_terms.json').read_text(encoding='utf-8'))
manual_sources={r['id'].split(':',1)[1]:r for r in resources if r['source']=='manualkm.fds'}
entries=[]
for chapter,replacements in manual_mapping.items():
    source=manual_sources[chapter]
    en=source['en'].removesuffix('\0')
    zh=en
    for replacement in replacements:
        old,new=replacement['en'],replacement['zh']
        assert zh.count(old)==1,(chapter,old,zh.count(old))
        zh=zh.replace(old,new,1)
    entries.append({'id':'manual.'+chapter,'en':en,'zh':zh,'source':'manualkm.fds',
                    'source_ids':[source['id']],'status':'translated_not_visual_verified'})
(ROOT/'translations/manual.json').write_text(json.dumps({'language':'zh-CN','entries':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('manual.json',len(entries))
