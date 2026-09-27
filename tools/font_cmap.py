"""Read Unicode cmap entries from trusted project TTF assets without extra dependencies."""
import struct

def cmap_glyph(font,codepoint):
    u16=lambda p:struct.unpack_from('>H',font,p)[0]
    u32=lambda p:struct.unpack_from('>I',font,p)[0]
    cmap=None
    for i in range(u16(4)):
        offset=12+16*i
        if font[offset:offset+4]==b'cmap':cmap=u32(offset+8);break
    if cmap is None:return 0
    for i in range(u16(cmap+2)):
        record=cmap+4+8*i
        platform,encoding=u16(record),u16(record+2)
        if not (platform==0 or (platform==3 and encoding in (1,10))):continue
        table=cmap+u32(record+4);kind=u16(table)
        if kind==12:
            for j in range(u32(table+12)):
                first,last,glyph=struct.unpack_from('>III',font,table+16+12*j)
                if first<=codepoint<=last:return glyph+codepoint-first
        elif kind==4 and codepoint<=65535:
            count=u16(table+6)//2;ends=table+14;starts=ends+2*count+2
            deltas=starts+2*count;ranges=deltas+2*count
            for j in range(count):
                if u16(starts+2*j)<=codepoint<=u16(ends+2*j):
                    delta=u16(deltas+2*j);distance=u16(ranges+2*j)
                    if distance==0:return (codepoint+delta)&65535
                    glyph=u16(ranges+2*j+distance+2*(codepoint-u16(starts+2*j)))
                    if glyph:return (glyph+delta)&65535
    return 0
