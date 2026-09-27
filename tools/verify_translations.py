"""Compare complete native runtime output, including generated item descriptions."""
from pathlib import Path
import json,os,re,shutil,struct,subprocess
from stage_preview import select,ROOT
from build_support import find_zig,compiler_environment

out=ROOT/'build/translation-tests';out.mkdir(exist_ok=True)
for name in ('fonts/ui.zhf','translations/ui.utf8'):
    target=out/'ExanimaZh'/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'build/preview-package/ExanimaZh'/name,target)
subprocess.run([str(find_zig()),'cc','-target','x86_64-windows-gnu','-DZH_VERIFY',
               '-O2','-Wall','-Wextra','-Werror',str(ROOT/'native/unicode_verify.c'),str(ROOT/'native/unicode.c'),
               '-lopengl32','-o',str(out/'verify.exe')],env=compiler_environment(),check=True)
enabled,_,_=select();cases=[]
for row in enabled:
    if not row.get('source_rva'):cases.append((row['en'],row['zh']))
    if '{Actor[' in row['en']:
        tokens=re.findall(r'\{Actor\[\d+\].Name\}',row['en'])
        assert len(tokens)==1
        for name,display in [('Elric','Elric'),('Anna-Maria','Anna-Maria'),("O'Brien","O'Brien"),
                             ('J\u00f6rg','J\u00f6rg'),('Fran\u00e7ois','Fran\u00e7ois'),('\x8aimon','\u0160imon')]:
            cases.append((row['en'].replace(tokens[0],name),row['zh'].replace(tokens[0],display)))
grammar=json.loads((ROOT/'translations/item_grammar.json').read_text(encoding='utf-8'))
bases={r['en'][11:]:r['zh'] for r in enabled if r['en'].startswith('@item.base:')}
for base in ('elegant shirt','pair of leather shoes','pair of cloth trousers'):
    for quality,qzh in grammar['quality'].items():
        for condition,czh in grammar['condition'].items():
            cases.append((f'A {quality} {base} {condition}.',f'{bases[base]}，{qzh}，{czh}。'))
            plural=base.startswith('pair of ')
            cases.append((f'A {base}. '+('They are ' if plural else 'It is ')+f'{quality}, but {condition}.',f'{bases[base]}，{qzh}，但{czh}。'))
            if plural:cases.append((f'A pair of {quality} {base[8:]} {condition}.',f'{bases[base]}，{qzh}，{czh}。'))
for mod,mzh in grammar['modifier'].items():
    cases.append((f'A well made {mod} elegant shirt in good condition.',f'{bases["elegant shirt"]}，{mzh}，做工精良，状态良好。'))
for base,zh in bases.items():
    for quality,condition in [('well made','in good condition'),('crudely made','in poor condition')]:
        # Model the engine's final quality sentence, including multi-sentence descriptions.
        text=base[0].upper()+base[1:]+'. It is '+quality+' and '+condition+'.'
        # Only bases originally beginning with uppercase "This/When" retain that case.
        if not base.startswith(('This ','When ')):text='A '+base+'. It is '+quality+' and '+condition+'.'
        cases.append((text,zh+'，'+grammar['quality'][quality]+'，'+grammar['condition'][condition]+'。'))
templates=json.loads((ROOT/'translations/message_templates.json').read_text(encoding='utf-8'))
rank=next(r['zh'] for r in enabled if r['en']=='Aspirant')
for source,target in templates.items():
    for n in ('1','42','99999999'):
        en,zh=source,target
        for token in re.findall(r'\{[nrsmi][0-3]\}',en):
            a,b=(n,n) if token[1]=='n' else ('Aspirant',rank) if token[1]=='r' else ('duel','决斗') if token[1]=='m' else ('sword','剑') if token[1]=='i' else ("O'Brien","O'Brien")
            zh=zh.replace(token,b);en=en.replace(token,a)
        cases.append((en,zh))
# Independent outputs from the engine's match-type tables, including lowercase
# conversion before adding the article (RVA 0x1970a0), not fabricated rank names.
for mode,zh in {'duel':'决斗','doubles':'双人','skirmish':'小队战','fray':'混战','reserve':'替补战',
                'pugilism':'拳斗','challenger':'挑战者','elimination':'淘汰','valiance':'勇战',
                'valour':'英勇','captain':'队长','brawl':'斗殴','beast':'巨兽'}.items():
    article='an' if mode[0] in 'aeiou' else 'a'
    for enprefix,zhprefix in [('You have won','你赢得了一场'),('You have lost','你输掉了一场'),('You forfeited','你弃权了一场')]:
        cases.append((f'{enprefix} {article} {mode} match.',f'{zhprefix}{zh}比赛。'))
cases.extend([('Entered 2/6','已报名 2/6'),('Nupizia (Aspirant)',f'Nupizia（{rank}）'),
              ('J\u00f6rg (Aspirant)',f'J\u00f6rg（{rank}）'),('Fran\u00e7ois has died.','Fran\u00e7ois已经死亡。'),
              ('\x8aimon has died.','\u0160imon已经死亡。')])
base='plate armour. It is made from a metal similar to brass, but while heavy, it serves its purpose well'
cases.append(('A well made plate armour in good condition. It is made from a metal similar to brass, but while heavy, it serves its purpose well.',
              bases[base]+'，做工精良，状态良好。'))
for row in json.loads((ROOT/'translations/manual.json').read_text(encoding='utf-8'))['entries']:
    tokens=set(re.findall(r'\[inpt\d+\]',row['en']))
    if not tokens:continue
    for key in ('Shift','Q','Mouse 4','Left Ctrl','F12'):
        en,zh=row['en'],row['zh']
        for i,token in enumerate(sorted(tokens)):
            # Different values within the same chapter must not be conflated.
            value=key if i==0 else 'Right Alt'
            en=en.replace(token,value);zh=zh.replace(token,value)
        cases.append((en,zh))
        cases.append((en+'Unexpected appended body.',''))
    bad=row['en'].replace(next(iter(tokens)),'[nope=1]')
    cases.append((bad,''))
cases.extend((s,'') for s in ('You have won an Aspirant match.','You have won a unknown match.',
                             'I found a totally unknown artifact.','Fred (Unrecognised)',
                             'Entered 2/unknown','Entered 2/6 extra'))
# EXE 0x33a370..0x33a6f0 contains these twenty phrases before [a]/[i]
# replacement. Test each real alternative rather than mirroring @format rows.
pickup_phrases=[
 ('I found [a].','我找到{item}了。'),("There's [a] here.",'这里有{item}。'),
 ('Found [a] here.','在这里找到{item}了。'),('Got [a] here.','这里有{item}。'),
 ('[a] here, if you want it.','这里有{item}，想要就拿去。'),('This [i] could be useful.','{item}也许用得上。'),
 ('I found some [i].','我找到一些{item}。'),("There's some [i] here.",'这里有一些{item}。'),
 ('Found some [i] here.','在这里找到一些{item}。'),('Got some [i] here.','这里有一些{item}。'),
 ('Some [i] here, if you want them.','这里有一些{item}，想要就拿去。'),('These [i] could be useful.','这些{item}也许用得上。'),
 ('And [a].','还有{item}。'),('Found [a] too.','还找到了{item}。'),('Also found [a].','还找到了{item}。'),("There's [a] too.",'还有{item}。'),
 ('And some [i].','还有一些{item}。'),('Found some [i] too.','还找到了一些{item}。'),
 ('Also found some [i].','还找到了一些{item}。'),("There's some [i] too.",'还有一些{item}。')]
captured={r['en']:r['zh'] for r in enabled if not r.get('source_rva')}
for source,target in pickup_phrases:
    for name,zh in [('sword','剑'),('axe','斧'),('leather trousers','皮裤'),
                    ('light tunic',captured['Light Tunic']),('heavy helmet',captured['Heavy Helmet'])]:
        article='an' if name[0] in 'aeiou' else 'a'
        text=source.replace('[a]',article+' '+name).replace('[i]',name)
        cases.append((text[0].upper()+text[1:],target.format(item=zh)))
names=json.loads((ROOT/'translations/item_names.json').read_text(encoding='utf-8'))
for modifier,mzh in grammar['modifier'].items():
    name=f'{modifier.capitalize()} Sword'
    cases.append((name,captured.get(name,mzh+names['Sword'])))
    cases.append((f'I found a {modifier} sword.',f'我找到{captured.get(name,mzh+names["Sword"])}了。'))
cases.extend((s,'') for s in ('Tournament begins in -2 days.','Tournament begins in 999999999 days.',
                             'Fred has reached Unrecognised rank.','[tcol=x]Fred has died.','has died.'))
cases.extend((s,'') for s in ('A well made totally unknown artifact in good condition.','untranslated dialogue', 'x'*7999,'x'*8000,'x'*65537,''))
blob=bytearray(struct.pack('<I',len(cases)))
for en,zh in cases:
    a=en.encode('latin-1');b=zh.encode('utf-8');blob+=struct.pack('<II',len(a),len(b))+a+b
(out/'cases.bin').write_bytes(blob)
run=subprocess.run([str(out/'verify.exe'),'--translations',str(out/'cases.bin')],capture_output=True,timeout=60)
report={'cases':len(cases),'exit_code':run.returncode,'stdout':run.stdout.decode('utf-8',errors='replace'),'stderr':run.stderr.decode('utf-8',errors='replace'),'visual_verified':False}
(out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(run.returncode)
