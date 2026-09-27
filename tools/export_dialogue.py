"""Extract bounded length-prefixed dialogue candidates; never rewrite scripts."""
from pathlib import Path
import json,re,struct,hashlib
from game_source import parse_game_files
ROOT=Path(__file__).resolve().parents[1]

def scan(data,name):
    rows=[]
    for offset in range(4,len(data)-2):
        length=struct.unpack_from('<I',data,offset-4)[0]
        if not 2<=length<=32768 or offset+length>len(data):continue
        raw=data[offset:offset+length]
        # Dialogue uses Windows-1252, including accented words such as façade.
        # Validate printable decoded characters, but retain the original bytes
        # below: the renderer's matcher compares bytes, not Unicode source text.
        try: decoded=raw.decode('cp1252')
        except UnicodeDecodeError: continue
        if not all(c.isprintable() or c in '\r\n\t' for c in decoded):continue
        text=raw.decode('latin-1') # Preserve source bytes used by the runtime matcher.
        if not re.search('[A-Za-z]{2}',text):continue
        script=bool(re.search(r'(^|\n)\s*(?:result\s*=|Actor(?:\[|\.)|Role\.|\?|ActivateTopic|GameEvent)|;|\$[0-9A-F]|TopicUsed\(',text))
        rows.append({'id':f'{name}:{offset}','source':name,'offset':offset,'length':length,'en':text,'kind':'script' if script else 'candidate'})
    return rows

def main():
    game=parse_game_files(__doc__)
    from exanima_zh import extract_entry
    data=extract_entry(game.rpk,'charroles.rdb')
    rows=scan(data,'charroles.rdb')
    out=ROOT/'build/catalog';out.mkdir(parents=True,exist_ok=True)
    (out/'dialogue-sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    candidates=[r for r in rows if r['kind']=='candidate']
    (out/'dialogue-review.txt').write_text('\n'.join(f"{r['offset']} {r['en']!r}" for r in candidates),encoding='utf-8')
    print(json.dumps({'records':len(rows),'candidates':len(candidates),'source_sha256':hashlib.sha256(data).hexdigest()}))
if __name__=='__main__':main()
