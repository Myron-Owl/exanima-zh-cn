"""Unicode atlas preparation; engine rendering remains a separate M1 step."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
from PIL import Image,ImageDraw,ImageFont
from font_cmap import cmap_glyph
ROOT=Path(__file__).resolve().parents[1]

def build(characters,size,page_size,out):
    font_path=ROOT/'assets/fonts/NotoSerifSC.ttf'
    fallback_path=ROOT/'assets/fonts/NotoSerifLatin.ttf'
    font_bytes=font_path.read_bytes();fallback_bytes=fallback_path.read_bytes()
    primary=ImageFont.truetype(str(font_path),size)
    fallback=ImageFont.truetype(str(fallback_path),size)
    out.mkdir(parents=True,exist_ok=True)
    pages=[Image.new('L',(page_size,page_size))]
    x=y=row_height=2
    glyphs=[]
    for char in sorted(characters,key=ord):
        use_fallback=not cmap_glyph(font_bytes,ord(char))
        if use_fallback and not cmap_glyph(fallback_bytes,ord(char)):
            raise ValueError(f'No actual font glyph: {char!r}')
        font=fallback if use_fallback else primary
        left,top,right,bottom=font.getbbox(char,anchor='ls')
        width=max(1,right-left);height=max(1,bottom-top)
        if width+4>page_size or height+4>page_size: raise ValueError('Glyph exceeds atlas page')
        if x+width+2>page_size: x=2;y+=row_height+2;row_height=2
        if y+height+2>page_size: pages.append(Image.new('L',(page_size,page_size)));x=y=row_height=2
        tile=Image.new('L',(width,height))
        ImageDraw.Draw(tile).text((-left,-top),char,font=font,fill=255,anchor='ls')
        if not char.isspace() and tile.getbbox() is None: raise ValueError(f'Empty glyph: {char!r}')
        pages[-1].paste(tile,(x,y))
        glyphs.append({'codepoint':ord(char),'page':len(pages)-1,'x':x,'y':y,
                       'width':width,'height':height,'bearing_x':left,'bearing_y':top,
                       'advance_64':round(font.getlength(char)*64),
                       'source_font':fallback_path.name if use_fallback else font_path.name})
        x+=width+2;row_height=max(row_height,height)
    for i,page in enumerate(pages):
        page.save(out/f'page-{i:03}.png')
        (out/f'page-{i:03}.a8').write_bytes(b'ZHA8'+struct.pack('<II',page_size,page_size)+page.tobytes())
    meta={'format':1,'font_sha256':hashlib.sha256(font_path.read_bytes()).hexdigest(),
          'fallback_font_sha256':hashlib.sha256(fallback_bytes).hexdigest(),
          'license':'SIL OFL 1.1','pixel_size':size,'page_size':page_size,'page_count':len(pages),
          'row_order':'top_to_bottom','bearing_origin':'baseline','glyphs':glyphs}
    (out/'metrics.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Reopen generated files and verify every glyph rectangle, page and byte count.
    for g in glyphs:
        assert g['x']+g['width']<=page_size and g['y']+g['height']<=page_size
        assert 0<=g['page']<len(pages)
    for i,page in enumerate(pages):
        blob=(out/f'page-{i:03}.a8').read_bytes()
        assert len(blob)==12+page_size*page_size and blob[12:]==page.tobytes()
    return meta

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-paging',action='store_true');args=parser.parse_args()
    provenance=json.loads((ROOT/'assets/fonts/provenance.json').read_text(encoding='utf-8'))
    for name,record in provenance.items():
        data=(ROOT/'assets/fonts'/name).read_bytes()
        assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256'],name
    from stage_preview import select
    selected,_,_=select()
    text=''.join(re.sub(r'\[/?[^\]]+\]','',r['zh']) for r in selected)
    # Runtime name placeholders preserve Windows-1252 characters. Include their
    # glyphs even when they do not happen to occur in a Chinese dictionary row.
    # Otherwise names such as François make the whole translated line fall back.
    name_chars={bytes([i]).decode('cp1252',errors='ignore') for i in range(32,256)}
    name_chars={c for c in name_chars if c and (c.isprintable() or c.isspace())}
    chars=name_chars|set(text)-{'\r','\n','\t'}
    report=[]
    for size in (16,24,32,48):
        meta=build(chars,size,2048,ROOT/f'build/fonts/{size}px')
        report.append({'pixel_size':size,'glyphs':len(chars),'pages':meta['page_count']})
    if args.verify_paging:
        # Force page transitions with real glyph data at a small test page size.
        meta=build(chars,32,128,ROOT/'build/fonts/paging-test')
        assert meta['page_count']>1
        report.append({'paging_test_pages':meta['page_count'],'roundtrip_verified':True})
    preview=Image.new('RGB',(760,260),'#191a1c');draw=ImageDraw.Draw(preview)
    font=ImageFont.truetype(str(ROOT/'assets/fonts/NotoSerifSC.ttf'),26)
    for i,line in enumerate(['音量：  100%','着色质量：  高','显示游戏提示    窗口模式','恢复默认    应用    取消','切换战斗状态    施放异能']):
        draw.text((24,14+i*48),line,font=font,fill='#dacdac')
    preview.save(ROOT/'build/fonts/preview.png')
    (ROOT/'build/fonts/verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
