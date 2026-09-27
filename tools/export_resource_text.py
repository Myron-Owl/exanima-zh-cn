"""Extract exact length-prefixed strings and manual chapters, without rewriting archives."""
from pathlib import Path
import collections,json,re,struct
from game_source import parse_game_files
ROOT=Path(__file__).resolve().parents[1]
def scan(data,name):
    rows=[]
    found=set()
    # Candidate starts may include a tab/CR byte belonging to the length field.
    for m in re.finditer(rb'[\x20-\x7e\r\n\t]{3,}',data):
        for offset in range(m.start(),min(m.start()+5,m.end())):
            if offset<4:continue
            n=struct.unpack_from('<I',data,offset-4)[0]
            if n<3 or offset+n>len(data):continue
            raw=data[offset:offset+n]
            if not re.fullmatch(rb'[\x20-\x7e\r\n\t]+',raw) or not re.search(rb'[A-Za-z]{3}',raw):continue
            if offset in found:continue
            found.add(offset)
            rows.append({'id':name+':'+str(offset),'source':name,'offset':offset,'length':n,'en':raw.decode('ascii'),'extraction':'u32_length_prefixed'})
    return rows


def main():
    game=parse_game_files(__doc__)
    from exanima_zh import read_rpk_index,extract_entry
    out=ROOT/'build/catalog';out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for entry in read_rpk_index(game.rpk)[1]:
        suffix=Path(entry.name).suffix
        if suffix in ('.pwr','.rcd'):
            rows.extend(scan(extract_entry(game.rpk,entry.name),entry.name))
        elif suffix=='.fds':
            path=out/entry.name;path.write_bytes(extract_entry(game.rpk,entry.name))
            for chapter in read_rpk_index(path)[1]:
                raw=extract_entry(path,chapter.name)
                rows.append({'id':entry.name+':'+chapter.name,'source':entry.name,'en':raw.decode('cp1252'),'extraction':'whole_manual_chapter'})
    (out/'resource-sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'resource-review.txt').write_text('\n'.join(r['id']+' '+repr(r['en']) for r in rows),encoding='utf-8')
    print(json.dumps(dict(collections.Counter(r['source'] for r in rows)),indent=2))


if __name__=='__main__':main()
