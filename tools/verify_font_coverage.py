"""Verify real font cmap coverage, not just a non-empty .notdef bitmap."""
from pathlib import Path
import json, re
from stage_preview import select
from font_cmap import cmap_glyph

ROOT=Path(__file__).resolve().parents[1]

def main():
    rows,_,_=select()
    text=''.join(re.sub(r'\[/?[^\]]+\]','',r['zh']) for r in rows)
    names={bytes([i]).decode('cp1252',errors='ignore') for i in range(32,256)}
    names={c for c in names if c and (c.isprintable() or c.isspace())}
    required=(names|set(text))-{'\r','\n','\t'}
    font=(ROOT/'assets/fonts/NotoSerifSC.ttf').read_bytes()
    fallback=(ROOT/'assets/fonts/NotoSerifLatin.ttf').read_bytes()
    using_fallback=sorted(c for c in required if not cmap_glyph(font,ord(c)))
    missing_source=[c for c in using_fallback if not cmap_glyph(fallback,ord(c))]
    metrics=json.loads((ROOT/'build/fonts/32px/metrics.json').read_text())
    atlas={g['codepoint'] for g in metrics['glyphs']}
    missing_atlas=sorted(c for c in required if ord(c) not in atlas)
    report={'required_characters':len(required),'cp1252_name_characters':len(names),
        'font_cmap_missing':missing_source,'atlas_missing':missing_atlas,'fallback_characters':using_fallback,
        'atlas_pages':metrics['page_count'],'visual_verified':False}
    (ROOT/'build/font-coverage-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert not missing_source and not missing_atlas

if __name__=='__main__':main()
