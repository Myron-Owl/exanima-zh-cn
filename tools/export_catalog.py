"""Version-checked source catalog. Never overwrites edited translations."""
from pathlib import Path
import json
import struct
from game_source import parse_game_files
ROOT=Path(__file__).resolve().parents[1]


def main():
    game=parse_game_files(__doc__)
    from exanima_zh import EXE_STRING_PATTERN,read_rpk_index,extract_entry,read_rdb
    catalog=[]
    for match in EXE_STRING_PATTERN.finditer(game.exe.read_bytes()):
        data=match.group(2)
        if struct.unpack('<Q',match.group(1))[0]!=len(data): continue
        try: text=data.decode('ascii')
        except UnicodeDecodeError: continue
        if not any(c.isalpha() for c in text): continue
        catalog.append({'id':f'exe:{match.start(2):08x}','source':'Exanima.exe',
                        'offset':match.start(2),'en':text})
    _,entries,_=read_rpk_index(game.rpk)
    for entry in entries:
        if not entry.name.endswith('.rdb'): continue
        try: _,rows=read_rdb(extract_entry(game.rpk,entry.name))
        except ValueError: continue
        for i,(key,flags,data) in enumerate(rows):
            catalog.append({'id':f'{entry.name}:{i}','source':entry.name,'key':key,'flags':flags,
                            'en':data.decode('cp1252',errors='replace')})
    out=ROOT/'build/catalog';out.mkdir(parents=True,exist_ok=True)
    (out/'sources.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'exe-review.txt').write_text('\n'.join(f"{r['id']} {r['en']!r}" for r in catalog if r['source']=='Exanima.exe'),encoding='utf-8')
    counts={source:sum(r['source']==source for r in catalog) for source in sorted({r['source'] for r in catalog})}
    print(json.dumps(counts,indent=2))


if __name__=='__main__':main()
