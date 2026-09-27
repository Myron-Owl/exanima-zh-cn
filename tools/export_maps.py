"""Read referenced map strings from embedded RDB indexes; never rewrite maps.

The last 16-byte slot is not a string record in this version. Earlier slots are
either empty or (0, 1, pool_offset, byte_length). Pool offsets start after the
entire index, including the last slot. Unreferenced old revisions in the pool
are deliberately not counted as active text.
"""
from pathlib import Path
import json,re,struct
from game_source import parse_game_files
ROOT=Path(__file__).resolve().parents[1]


def main():
    game=parse_game_files(__doc__)
    from exanima_zh import read_rpk_index,extract_entry
    rows=[];indexes=[]
    for entry in read_rpk_index(game.rpk)[1]:
        if not entry.name.endswith('.rfc'):continue
        data=extract_entry(game.rpk,entry.name)
        for match in re.finditer(bytes.fromhex('020cbfaf'),data):
            start=match.start();size=struct.unpack_from('<I',data,start+4)[0];base=start+8+size
            assert size>=16 and size%16==0 and base<=len(data),entry.name
            for i in range(size//16-1):
                a,flags,offset,length=struct.unpack_from('<4I',data,start+8+i*16)
                if (a,flags,offset,length)==(0,0,0,0):continue
                assert a==0 and flags==1 and length and base+offset+length<=len(data),(entry.name,i)
                raw=data[base+offset:base+offset+length]
                assert all(c in (9,10,13) or 32<=c<=126 or c in (0x85,0x91,0x92,0x93,0x94,0xae) for c in raw),(entry.name,i)
                rows.append({'id':entry.name+':rdb:'+str(i),'source':entry.name,'offset':base+offset,'length':length,'en':raw.decode('latin-1'),'extraction':'embedded_rdb_index'})
            indexes.append({'source':entry.name,'offset':start,'slots':size//16-1})
    out=ROOT/'build/catalog';out.mkdir(parents=True,exist_ok=True)
    (out/'map-sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'map-review.txt').write_text('\n\n'.join(r['id']+' '+repr(r['en']) for r in rows),encoding='utf-8')
    (out/'map-indexes.json').write_text(json.dumps(indexes,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'map_indexes':len(indexes),'referenced_records':len(rows),'unique_texts':len({r['en'] for r in rows})}))


if __name__=='__main__':main()
