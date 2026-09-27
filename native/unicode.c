#define WIN32_LEAN_AND_MEAN
#include "unicode.h"
#include <GL/gl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

typedef struct { uint32_t codepoint,page,x,y,width,height; int32_t bearing_x,bearing_y,advance_64; } Glyph;
typedef struct { char *source; uint32_t *points; size_t count,length; uint64_t hash; uint32_t source_rva; } Translation;
static Translation dictionary[8192];
static size_t dictionary_count;
static unsigned char *font_data,*image_base;
static Glyph *glyphs;
static uint32_t glyph_count,page_count,page_size,pixel_size;
static GLuint textures[64];
static HGLRC texture_context;
static ZhLogger write_log;
static BOOL texture_failure, draw_logged;
static uint64_t text_hash(const char *s,size_t n) {
    uint64_t h=1469598103934665603ULL;
    for(size_t i=0;i<n;i++) h=(h^(unsigned char)s[i])*1099511628211ULL;
    return h;
}
static int compare_rows(const void *a,const void *b) {
    uint64_t x=((const Translation*)a)->hash,y=((const Translation*)b)->hash;
    return x<y?-1:x>y?1:0;
}
static BOOL unescape(char *text) {
    char *out=text;
    while(*text) {
        if(*text=='\\') {
            text++;
            if(*text=='n') {*out++='\n';text++;}else if(*text=='r') {*out++='\r';text++;}
            else if(*text=='t') {*out++='\t';text++;}else if(*text=='\\') {*out++='\\';text++;}
            else if(*text=='x') {
                int value=0;text++;
                for(int i=0;i<2;i++,text++) {
                    char c=*text;int digit=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;
                    if(digit<0) return FALSE;value=value*16+digit;
                }
                if(!value) return FALSE;*out++=(char)value;
            } else return FALSE;
        } else *out++=*text++;
    }
    *out=0;return TRUE;
}
static unsigned char *read_asset(HMODULE module,const wchar_t *relative,DWORD limit,DWORD *size) {
    wchar_t path[MAX_PATH];DWORD n=GetModuleFileNameW(module,path,MAX_PATH);
    if(!n || n>=MAX_PATH) return NULL;
    wchar_t *slash=wcsrchr(path,L'\\');
    if(!slash || (size_t)(slash-path)+wcslen(relative)+2>=MAX_PATH) return NULL;
    wcscpy(slash+1,relative);
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    if(file==INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER length; unsigned char *data=NULL;DWORD got;
    if(GetFileSizeEx(file,&length) && length.QuadPart>0 && length.QuadPart<=limit) {
        data=malloc((size_t)length.QuadPart+1);
        if(data && (!ReadFile(file,data,(DWORD)length.QuadPart,&got,NULL) || got!=length.QuadPart)) {free(data);data=NULL;}
        if(data) {data[got]=0;*size=got;}
    }
    CloseHandle(file);return data;
}
static const Glyph *find_glyph(uint32_t codepoint) {
    size_t low=0,high=glyph_count;
    while(low<high) {size_t mid=(low+high)/2; if(glyphs[mid].codepoint<codepoint) low=mid+1;else high=mid;}
    return low<glyph_count && glyphs[low].codepoint==codepoint ? glyphs+low : NULL;
}
static BOOL manual_header(const char *text,size_t length,const char **header,size_t *header_length) {
    size_t start=0;
    while(start<length && (text[start]=='\r' || text[start]=='\n')) start++;
    static const char prefix[]="[algn=2][tcol=FFE399]";
    if(length-start<sizeof(prefix)-1 || memcmp(text+start,prefix,sizeof(prefix)-1)) return FALSE;
    const char *end=NULL;
    for(size_t i=start+sizeof(prefix)-1;i+7<=length && i<start+128;i++)
        if(!memcmp(text+i,"[/tcol]",7)) {end=text+i+7;break;}
    if(!end) return FALSE;
    *header=text+start;*header_length=(size_t)(end-(text+start));return TRUE;
}
static const Translation *lookup_exact_span(const char *source,size_t length) {
    uint64_t hash=text_hash(source,length);
    size_t lo=0,hi=dictionary_count;
    while(lo<hi) {size_t mid=(lo+hi)/2;if(dictionary[mid].hash<hash) lo=mid+1;else hi=mid;}
    const Translation *fallback=NULL;
    for(size_t i=lo;i<dictionary_count && dictionary[i].hash==hash;i++) {
        if(dictionary[i].length!=length || memcmp(source,dictionary[i].source,length)) continue;
        if(dictionary[i].source_rva) {
            if(image_base && source==(const char*)image_base+dictionary[i].source_rva) return dictionary+i;
        } else fallback=dictionary+i;
    }
    return fallback;
}
typedef struct {Translation row;uint32_t points[2048];} DynamicTranslation;
static __thread DynamicTranslation dynamic_rows[8];
static __thread unsigned dynamic_row_cursor;
static const Translation *item_quality[64],*item_condition[64],*item_modifier[32],*actor_templates[256],*message_templates[128];
static size_t quality_count,condition_count,modifier_count,actor_count,message_count;
static DynamicTranslation *new_dynamic(const char *source,size_t length) {
    DynamicTranslation *slot=dynamic_rows+(dynamic_row_cursor++%8);
    memset(&slot->row,0,sizeof(slot->row));slot->row.source=(char*)source;slot->row.length=length;
    slot->row.hash=text_hash(source,length);slot->row.points=slot->points;return slot;
}
static BOOL append_translation(DynamicTranslation *slot,const Translation *row,size_t limit) {
    if(!row || limit>row->count || slot->row.count+limit>sizeof(slot->points)/sizeof(slot->points[0])-8) return FALSE;
    memcpy(slot->points+slot->row.count,row->points,limit*sizeof(uint32_t));slot->row.count+=limit;return TRUE;
}
static void trim_item(char *text) {
    size_t n=strlen(text);
    while(n && (text[n-1]==' ' || text[n-1]=='.' || text[n-1]==',')) text[--n]=0;
    const char *empty_suffixes[]={" It is"," They are"," and"," but"};
    for(size_t i=0;i<4;i++) {
        size_t k=strlen(empty_suffixes[i]);
        if(n>=k && !memcmp(text+n-k,empty_suffixes[i],k)) {text[n-k]=0;trim_item(text);return;}
    }
}
static const Translation *item_base(const char *text) {
    if(!strncmp(text,"A ",2)) text+=2;else if(!strncmp(text,"An ",3)) text+=3;
    char key[8192];size_t n=strlen(text);
    if(n+12>=sizeof(key)) return NULL;
    memcpy(key,"@item.base:",11);
    memcpy(key+11,text,n+1);
    trim_item(key);
    return lookup_exact_span(key,strlen(key));
}
static const Translation *match_item_term(const Translation **rules,size_t count,size_t prefix,
                                        const char *text,size_t *matched) {
    const Translation *best=NULL;*matched=0;
    for(size_t i=0;i<count;i++) {
        const char *key=rules[i]->source+prefix;size_t n=rules[i]->length-prefix;
        if(n>*matched && !strncmp(text,key,n) && (!text[n] || text[n]==' ' || text[n]=='.' || text[n]==',')) {best=rules[i];*matched=n;}
    }
    return best;
}
static const Translation *lookup_item_description(const char *source,size_t length) {
    if(length>=8000 || memchr(source,'[',length) || memchr(source,'{',length)) return NULL;
    char text[8192];memcpy(text,source,length);text[length]=0;
    const Translation *condition=NULL,*quality=NULL,*mods[8];size_t mod_count=0;
    BOOL contrast=FALSE;
    // The engine appends wear either before the first full stop or in an
    // "It is ... and/but ..." sentence. Remove only a verified whole clause.
    for(size_t i=0;i<length;i++) {
        if(i && text[i-1]!=' ') continue;
        size_t n;const Translation *term=match_item_term(item_condition,condition_count,16,text+i,&n);
        if(!term || (text[i+n] && text[i+n]!='.')) continue;
        condition=term;size_t start=i;
        if(start>=6 && !memcmp(text+start-6,", but ",6)) {start-=6;contrast=TRUE;}
        else if(start>=5 && !memcmp(text+start-5," and ",5)) start-=5;
        else if(start && text[start-1]==' ') start--;
        memmove(text+start,text+i+n,strlen(text+i+n)+1);break;
    }
    trim_item(text);
    const Translation *base_row=item_base(text);
    // Quality can be before a noun, after "pair of", or in a final sentence.
    for(size_t attempt=0;!base_row && attempt<9;attempt++) {
        size_t pos=!strncmp(text,"A ",2)?2:!strncmp(text,"An ",3)?3:0;
        // The base description itself can contain "It is made from...".
        // Only the final added quality sentence is part of the engine grammar.
        char *tail=NULL,*next=text;size_t tail_term_length;
        while((next=strstr(next," It is "))!=NULL) {
            if(match_item_term(item_quality,quality_count,14,next+7,&tail_term_length)) tail=next;
            next++;
        }
        next=text;while((next=strstr(next," They are "))!=NULL) {
            if((!tail || next>tail) && match_item_term(item_quality,quality_count,14,next+10,&tail_term_length)) tail=next;
            next++;
        }
        if(tail) pos=(size_t)(tail-text)+(!strncmp(tail," It is ",7)?7:10);
        size_t n;const Translation *term=match_item_term(item_quality,quality_count,14,text+pos,&n);
        if(!term && !strncmp(text+pos,"pair of ",8)) {pos+=8;term=match_item_term(item_quality,quality_count,14,text+pos,&n);}
        if(term && !quality) quality=term;
        else {
            term=match_item_term(item_modifier,modifier_count,15,text+pos,&n);
            if(!term || mod_count==8) break;
            mods[mod_count++]=term;
        }
        if(text[pos+n]==' ') n++;
        memmove(text+pos,text+pos+n,strlen(text+pos+n)+1);trim_item(text);base_row=item_base(text);
    }
    if(!base_row) return NULL;
    DynamicTranslation *slot=new_dynamic(source,length);
    if(!append_translation(slot,base_row,base_row->count)) return NULL;
    for(size_t i=0;i<mod_count+2;i++) {
        const Translation *part=i<mod_count?mods[i]:i==mod_count?quality:condition;
        if(!part) continue;
        slot->points[slot->row.count++]=0xff0c;
        if(part==condition && contrast) slot->points[slot->row.count++]=0x4f46;
        if(!append_translation(slot,part,part->count)) return NULL;
    }
    slot->points[slot->row.count++]=0x3002;
    return &slot->row;
}
static const Translation *lookup_actor_text(const char *source,size_t length) {
    for(size_t i=0;i<actor_count;i++) {
        const Translation *row=actor_templates[i];
        const char *token=strstr(row->source,"{Actor[");const char *end=token?strchr(token,'}'):NULL;
        if(!end) continue;
        size_t prefix=(size_t)(token-row->source),token_length=(size_t)(end-token)+1,suffix=row->length-prefix-token_length;
        if(length<=prefix+suffix || length-prefix-suffix>128 || prefix+suffix<10 ||
           memcmp(source,row->source,prefix) || memcmp(source+length-suffix,end+1,suffix)) continue;
        size_t name_length=length-prefix-suffix;
        wchar_t name[128];int count=MultiByteToWideChar(1252,0,source+prefix,(int)name_length,name,128);
        if(count<1) continue;
        BOOL valid=TRUE;for(int k=0;k<count;k++) if(name[k]<32 || name[k]=='[' || name[k]==']' || name[k]=='{' || name[k]=='}' || !find_glyph(name[k])) valid=FALSE;
        if(!valid) continue;
        DynamicTranslation *slot=new_dynamic(source,length);
        for(size_t k=0;k<row->count;) {
            BOOL hit=k+token_length<=row->count;
            for(size_t j=0;hit && j<token_length;j++) if(row->points[k+j]!=(unsigned char)token[j]) hit=FALSE;
            if(slot->row.count+(hit?(size_t)count:1)>2040) {valid=FALSE;break;}
            if(hit) {for(int j=0;j<count;j++) slot->points[slot->row.count++]=name[j];k+=token_length;}
            else slot->points[slot->row.count++]=row->points[k++];
        }
        if(valid) return &slot->row;
    }
    return NULL;
}
static const Translation *lookup_named_value(const char *space,const char *value,size_t length) {
    char key[256];size_t prefix=strlen(space);
    if(!length || prefix+length>=sizeof(key)) return NULL;
    memcpy(key,space,prefix);
    for(size_t i=0;i<length;i++) {
        unsigned char c=(unsigned char)value[i];
        key[prefix+i]=(char)(c>='A' && c<='Z'?c+32:c);
    }
    key[prefix+length]=0;return lookup_exact_span(key,prefix+length);
}
static const Translation *lookup_item_name(const char *source,size_t length,BOOL require_modifier) {
    if(!length || length>=200) return NULL;
    char text[200];for(size_t i=0;i<length;i++) {unsigned char c=(unsigned char)source[i];text[i]=(char)(c>='A'&&c<='Z'?c+32:c);}text[length]=0;
    const Translation *base=lookup_named_value("@item.name:",text,length);
    if(base) return require_modifier?NULL:base;
    // 0.9.5.2 inserts exactly one prefix from its eight-entry modifier table.
    size_t n;const Translation *mod=match_item_term(item_modifier,modifier_count,15,text,&n);
    if(!mod || text[n]!=' ') return NULL;
    base=lookup_named_value("@item.name:",text+n+1,length-n-1);if(!base) return NULL;
    DynamicTranslation *slot=new_dynamic(source,length);
    if(!append_translation(slot,mod,mod->count)) return NULL;
    if(!append_translation(slot,base,base->count)) return NULL;
    return &slot->row;
}
static const Translation *lookup_manual(const char *source,size_t length) {
    const char *header;size_t header_length;
    if(!manual_header(source,length,&header,&header_length)) return NULL;
    for(size_t r=0;r<dictionary_count;r++) {
        const Translation *row=dictionary+r;const char *candidate;size_t candidate_length;
        if(!strstr(row->source,"[inpt") || !manual_header(row->source,row->length,&candidate,&candidate_length) ||
           candidate_length!=header_length || memcmp(candidate,header,header_length)) continue;
        // Capture only key substitutions. Every other source byte must match;
        // a heading alone cannot identify changed text or a controller chapter.
        uint32_t keys[32][64];size_t counts[32]={0};BOOL valid=TRUE;size_t pos=0;
        const char *pattern=row->source;
        while(*pattern && valid) {
            if(strncmp(pattern,"[inpt",5)) {
                if(pos>=length || source[pos]!=*pattern) {valid=FALSE;break;}
                pattern++;pos++;continue;
            }
            pattern+=5;unsigned index=0,digits=0;
            while(*pattern>='0' && *pattern<='9' && digits<2) {index=index*10+(unsigned)(*pattern++-'0');digits++;}
            if(!digits || index>=32 || *pattern++!=']') {valid=FALSE;break;}
            const char *next=strstr(pattern,"[inpt");size_t fixed=next?(size_t)(next-pattern):strlen(pattern),end=pos;
            if(!fixed) {valid=FALSE;break;}
            while(end+fixed<=length && memcmp(source+end,pattern,fixed)) end++;
            size_t n=end-pos;if(end+fixed>length || !n || n>63) {valid=FALSE;break;}
            wchar_t wide[64];int count=MultiByteToWideChar(1252,0,source+pos,(int)n,wide,64);
            if(count<1) {valid=FALSE;break;}
            for(int i=0;i<count;i++) if(wide[i]<32 || wide[i]=='[' || wide[i]==']' || wide[i]=='{' || wide[i]=='}' || !find_glyph(wide[i])) valid=FALSE;
            if(counts[index]) {
                if(counts[index]!=(size_t)count) valid=FALSE;
                for(int i=0;valid && i<count;i++) if(keys[index][i]!=(uint32_t)wide[i]) valid=FALSE;
            } else {counts[index]=(size_t)count;for(int i=0;i<count;i++) keys[index][i]=wide[i];}
            pos=end;
        }
        if(!valid || pos!=length) continue;
        DynamicTranslation *slot=new_dynamic(source,length);
        for(size_t i=0;i<row->count;) {
            if(i+5<row->count && row->points[i]=='[' && row->points[i+1]=='i' && row->points[i+2]=='n' && row->points[i+3]=='p' && row->points[i+4]=='t') {
                size_t j=i+5;unsigned index=0,digits=0;
                while(j<row->count && row->points[j]>='0' && row->points[j]<='9' && digits<2) {index=index*10+row->points[j++]-'0';digits++;}
                if(!digits || index>=32 || j>=row->count || row->points[j]!=']' || !counts[index] || slot->row.count+counts[index]>2040) {valid=FALSE;break;}
                memcpy(slot->points+slot->row.count,keys[index],counts[index]*sizeof(uint32_t));slot->row.count+=counts[index];i=j+1;
            } else {if(slot->row.count>=2040) {valid=FALSE;break;}slot->points[slot->row.count++]=row->points[i++];}
        }
        if(valid) return &slot->row;
    }
    return NULL;
}
static const Translation *lookup_message(const char *source,size_t length) {
    if(length>1024) return NULL;
    for(size_t r=0;r<message_count;r++) {
        const Translation *row=message_templates[r];
        const char *pattern=row->source+8;size_t pos=0;BOOL valid=TRUE;
        uint32_t values[4][256];size_t counts[4]={0};char kinds[4]={0};
        while(*pattern && valid) {
            if(*pattern!='{') {
                if(pos>=length || *pattern!=source[pos]) {valid=FALSE;break;}
                pattern++;pos++;continue;
            }
            if(strlen(pattern)<4 || !strchr("nrsmi",pattern[1]) || pattern[2]<'0' || pattern[2]>'3' || pattern[3]!='}') {valid=FALSE;break;}
            char kind=pattern[1];int index=pattern[2]-'0';pattern+=4;
            if(kinds[index]) {valid=FALSE;break;}kinds[index]=kind;
            size_t fixed=0;while(pattern[fixed] && pattern[fixed]!='{') fixed++;
            size_t end=pos;
            if(!*pattern) end=length;
            else {
                if(!fixed) {valid=FALSE;break;}
                while(end+fixed<=length && memcmp(source+end,pattern,fixed)) end++;
                if(end+fixed>length) {valid=FALSE;break;}
            }
            size_t n=end-pos;
            if(!n || n>128 || (kind=='n' && n>8)) {valid=FALSE;break;}
            for(size_t j=pos;j<end;j++) {
                unsigned char c=(unsigned char)source[j];
                if(c<32 || c=='{' || c=='}' || c=='[' || c==']' || (kind=='n' && (c<'0' || c>'9'))) valid=FALSE;
            }
            if(!valid) break;
            const Translation *translated=kind=='r'?lookup_exact_span(source+pos,n):NULL;
            if(kind=='m') translated=lookup_named_value("@match.type:",source+pos,n);
            if(kind=='i') translated=lookup_item_name(source+pos,n,FALSE);
            if(kind=='r' || kind=='m' || kind=='i') {
                if(!translated || translated->count>256) {valid=FALSE;break;}
                memcpy(values[index],translated->points,translated->count*sizeof(uint32_t));counts[index]=translated->count;
            } else {
                wchar_t wide[128];int count=MultiByteToWideChar(1252,0,source+pos,(int)n,wide,128);
                if(count<1) {valid=FALSE;break;}
                for(int j=0;j<count;j++) {if(!find_glyph(wide[j])) valid=FALSE;values[index][j]=wide[j];}
                counts[index]=(size_t)count;
            }
            pos=end;
        }
        if(!valid || pos!=length) continue;
        DynamicTranslation *slot=new_dynamic(source,length);
        for(size_t i=0;i<row->count;i++) {
            if(row->points[i]=='{' && i+3<row->count && row->points[i+3]=='}' && row->points[i+2]>='0' && row->points[i+2]<='3') {
                int index=(int)row->points[i+2]-'0';size_t n=counts[index];
                if(row->points[i+1]!=(uint32_t)kinds[index] || !n || slot->row.count+n>2040) {valid=FALSE;break;}
                memcpy(slot->points+slot->row.count,values[index],n*sizeof(uint32_t));slot->row.count+=n;i+=3;
            } else {
                if(slot->row.count>=2040) {valid=FALSE;break;}
                slot->points[slot->row.count++]=row->points[i];
            }
        }
        if(valid) return &slot->row;
    }
    return NULL;
}
static const Translation *lookup_span(const char *source,int64_t length) {
    if(!source) return NULL;
    if(length<1 || length>65536) return NULL;
    const Translation *exact=lookup_exact_span(source,(size_t)length);
    if(exact) return exact;
    const Translation *manual=lookup_manual(source,(size_t)length);if(manual) return manual;
    const Translation *actor=lookup_actor_text(source,(size_t)length);
    if(actor) return actor;
    const Translation *message=lookup_message(source,(size_t)length);
    if(message) return message;
    const Translation *item_name=lookup_item_name(source,(size_t)length,TRUE);
    return item_name?item_name:lookup_item_description(source,(size_t)length);
}
static const Translation *lookup(const char *source) {
    if(!source) return NULL;
    int64_t length;memcpy(&length,source-8,8);
    return lookup_span(source,length);
}
BOOL zh_has_translation(const char *source) {return lookup(source)!=NULL;}
#ifdef ZH_VERIFY
int zh_test_translate(const char *source,int length,char *out,int capacity) {
    const Translation *row=lookup_span(source,length);if(!row) return -1;
    wchar_t wide[65536];size_t n=0;
    for(size_t i=0;i<row->count;i++) {
        uint32_t cp=row->points[i];if(n+2>=65536) return -2;
        if(cp>=0x10000) {cp-=0x10000;wide[n++]=(wchar_t)(0xd800+(cp>>10));wide[n++]=(wchar_t)(0xdc00+(cp&1023));}
        else wide[n++]=(wchar_t)cp;
    }
    return WideCharToMultiByte(CP_UTF8,0,wide,(int)n,out,capacity,NULL,NULL);
}
#endif
BOOL zh_load(HMODULE module,unsigned char *image,ZhLogger logger) {
    image_base=image;write_log=logger;
    DWORD size=0;
    font_data=read_asset(module,L"ExanimaZh\\fonts\\ui.zhf",64*1024*1024,&size);
    if(!font_data || size<24 || memcmp(font_data,"ZHF1",4)) return FALSE;
    uint32_t *header=(uint32_t*)font_data;
    pixel_size=header[1];page_size=header[2];page_count=header[3];glyph_count=header[4];
    uint64_t metadata=24+(uint64_t)glyph_count*sizeof(Glyph);
    if(!pixel_size || pixel_size>128 || page_size<64 || page_size>4096 || !page_count || page_count>64 ||
       !glyph_count || glyph_count>65536 || metadata+(uint64_t)page_count*page_size*page_size!=size) return FALSE;
    glyphs=(Glyph*)(font_data+24);
    for(size_t i=0;i<glyph_count;i++) {
        Glyph *g=glyphs+i;
        if((i && glyphs[i-1].codepoint>=g->codepoint) || g->page>=page_count || g->x>=page_size || g->y>=page_size ||
           g->width>page_size-g->x || g->height>page_size-g->y || g->advance_64<0 || g->advance_64>32768 ||
           g->bearing_x < -128 || g->bearing_x>128 || g->bearing_y < -128 || g->bearing_y>128) return FALSE;
    }
    char *text=(char*)read_asset(module,L"ExanimaZh\\translations\\ui.utf8",16*1024*1024,&size);
    if(!text) return FALSE;
    if(memchr(text,0,size)) {free(text);return FALSE;}
    char *cursor=text;BOOL valid=TRUE;
    while(*cursor && valid) {
        char *next=strchr(cursor,'\n');if(next) *next++=0;
        size_t line_length=strlen(cursor);if(line_length && cursor[line_length-1]=='\r') cursor[--line_length]=0;
        if(line_length && cursor[0]!='#') {
            char *tab=strchr(cursor,'\t');
            if(!tab || tab==cursor || tab-cursor>131072 || dictionary_count>=8192) {valid=FALSE;break;}
            *tab++=0;Translation row={0};
            char *scope=strchr(tab,'\t');
            if(scope) {
                *scope++=0;char *end;unsigned long rva=strtoul(scope,&end,16);
                if(end==scope || *end || !rva || rva>0x600000) {valid=FALSE;break;}
                row.source_rva=(uint32_t)rva;
            }
            if(!unescape(cursor) || !unescape(tab) || strlen(cursor)>65536) {valid=FALSE;break;}
            row.length=strlen(cursor);row.hash=text_hash(cursor,row.length);
            int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,tab,-1,NULL,0);
            if(n<=1 || n>65536) {valid=FALSE;break;}
            wchar_t *wide=malloc((size_t)n*sizeof(wchar_t));
            row.source=_strdup(cursor);row.points=calloc((size_t)n,sizeof(uint32_t));
            if(!wide || !row.source || !row.points) {free(wide);free(row.source);free(row.points);valid=FALSE;break;}
            MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,tab,-1,wide,n);
            for(int j=0;j<n-1;j++) {
                uint32_t cp=wide[j];
                if(cp>=0xd800 && cp<=0xdbff) {uint32_t lo=wide[++j];cp=0x10000+((cp-0xd800)<<10)+(lo-0xdc00);}
                if((!find_glyph(cp) && cp!='\r' && cp!='\n' && cp!='\t') || (cp<32 && cp!='\r' && cp!='\n' && cp!='\t')) {valid=FALSE;break;}
                row.points[row.count++]=cp;
            }
            for(size_t j=0;j<dictionary_count;j++) if(!strcmp(dictionary[j].source,row.source) && dictionary[j].source_rva==row.source_rva) valid=FALSE;
            if(valid) dictionary[dictionary_count++]=row;
            else {free(row.source);free(row.points);}
            free(wide);
        }
        if(!next) break;cursor=next;
    }
    free(text);
    if(!valid || !dictionary_count) {dictionary_count=0;return FALSE;}
    qsort(dictionary,dictionary_count,sizeof(dictionary[0]),compare_rows);
    for(size_t i=0;i<dictionary_count;i++) {
        Translation *row=dictionary+i;
        if(!strncmp(row->source,"@item.quality:",14)) {if(quality_count==64) return FALSE;item_quality[quality_count++]=row;}
        if(!strncmp(row->source,"@item.condition:",16)) {if(condition_count==64) return FALSE;item_condition[condition_count++]=row;}
        if(!strncmp(row->source,"@item.modifier:",15)) {if(modifier_count==32) return FALSE;item_modifier[modifier_count++]=row;}
        if(strstr(row->source,"{Actor[") && strstr(row->source,"].Name}")) {if(actor_count==256) return FALSE;actor_templates[actor_count++]=row;}
        if(!strncmp(row->source,"@format:",8)) {if(message_count==128) return FALSE;message_templates[message_count++]=row;}
    }
    write_log("Unicode assets ready: %zu translations, %u glyphs, %u pages; rendering awaits a matching label.",dictionary_count,glyph_count,page_count);
    return TRUE;
}
static float scale_for(void *font) {
    if(!font) return 0;
    int cap=((int*)font)[4];
    return cap>0 && cap<=128 ? (float)cap/pixel_size : 0;
}
static float text_width(const Translation *row,float scale) {
    float width=0;
    for(size_t i=0;i<row->count;i++) {
        const Glyph *g=find_glyph(row->points[i]);
        if(!g || row->points[i]=='[') return -1;
        width+=g->advance_64*(scale/64.f);
    }
    return width;
}
int zh_width(const char *source,void *font) {
    const Translation *row=lookup(source);float scale=scale_for(font);
    if(!row || !scale || texture_failure) return -1;
    float width=text_width(row,scale);
    return width<0?-1:(int)(width+0.5f);
}
typedef void (APIENTRY *ActiveTextureFn)(GLenum);
typedef void (APIENTRY *BindBufferFn)(GLenum,GLuint);
static ActiveTextureFn active_texture;
static BOOL upload_textures(void) {
    HGLRC context=wglGetCurrentContext();
    if(!context || texture_failure) return FALSE;
    if(texture_context==context) return TRUE;
    PROC active_address=wglGetProcAddress("glActiveTexture");
    PROC buffer_address=wglGetProcAddress("glBindBuffer");
    BindBufferFn bind_buffer;
    memcpy(&active_texture,&active_address,sizeof(active_texture));
    memcpy(&bind_buffer,&buffer_address,sizeof(bind_buffer));
    if((uintptr_t)active_texture<4096 || (uintptr_t)bind_buffer<4096 ||
       (intptr_t)active_texture==-1 || (intptr_t)bind_buffer==-1) return FALSE;
    GLint active,bound,pbo,unpack,row,skip_rows,skip_pixels;
    glGetIntegerv(0x84e0,&active);active_texture(0x84c0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D,&bound);glGetIntegerv(0x88ef,&pbo);
    glGetIntegerv(GL_UNPACK_ALIGNMENT,&unpack);glGetIntegerv(GL_UNPACK_ROW_LENGTH,&row);
    glGetIntegerv(GL_UNPACK_SKIP_ROWS,&skip_rows);glGetIntegerv(GL_UNPACK_SKIP_PIXELS,&skip_pixels);
    size_t pixels=(size_t)page_size*page_size;
    unsigned char *rgba=malloc(pixels*4);
    if(!rgba) {active_texture(active);return FALSE;}
    bind_buffer(0x88ec,0);
    glPixelStorei(GL_UNPACK_ALIGNMENT,1);glPixelStorei(GL_UNPACK_ROW_LENGTH,0);
    glPixelStorei(GL_UNPACK_SKIP_ROWS,0);glPixelStorei(GL_UNPACK_SKIP_PIXELS,0);
    glGenTextures(page_count,textures);BOOL ok=TRUE;
    for(uint32_t page=0;page<page_count;page++) {
        const unsigned char *alpha=font_data+24+glyph_count*sizeof(Glyph)+page*pixels;
        for(size_t i=0;i<pixels;i++) {rgba[4*i]=rgba[4*i+1]=rgba[4*i+2]=255;rgba[4*i+3]=alpha[i];}
        glBindTexture(GL_TEXTURE_2D,textures[page]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,0x812f);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,0x812f);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,page_size,page_size,0,GL_RGBA,GL_UNSIGNED_BYTE,rgba);
        GLint width=0;glGetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);
        if(width!=(GLint)page_size || !textures[page]) ok=FALSE;
    }
    free(rgba);
    glBindTexture(GL_TEXTURE_2D,bound);glPixelStorei(GL_UNPACK_ALIGNMENT,unpack);
    glPixelStorei(GL_UNPACK_ROW_LENGTH,row);glPixelStorei(GL_UNPACK_SKIP_ROWS,skip_rows);
    glPixelStorei(GL_UNPACK_SKIP_PIXELS,skip_pixels);bind_buffer(0x88ec,pbo);active_texture(active);
    if(ok) texture_context=context;else texture_failure=TRUE;
    write_log("Unicode texture upload: %s, context=%p",ok?"OK":"FAILED - English fallback",context);
    return ok;
}
static BOOL draw_row(const Translation *row,float x,float y,BOOL batched,float max_width,float *right) {
    if(!row || !image_base) return FALSE;
    void *font=*(void**)(image_base+0x496650);float scale=scale_for(font);
    if(!row || !scale || text_width(row,scale)<0 || !upload_textures()) return FALSE;
    void (*begin)(void)=(void*)(image_base+0x1f6c00);
    void (*end)(void)=(void*)(image_base+0x1f6f10);
    void (*uv)(float,float)=(void*)(image_base+0x1f6de0);
    void (*vertex)(float,float)=(void*)(image_base+0x1f6ca0);
    if(batched && *(int*)(image_base+0x58ac20)>0) end();
    GLint active,bound;glGetIntegerv(0x84e0,&active);active_texture(0x84c0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D,&bound);
    uint32_t page=UINT32_MAX;float cursor=x;
    // Font bearings use a screen-space baseline. Keep descent inside the original quad.
    float baseline=y-4.f*scale;
    for(size_t i=0;i<row->count;i++) {
        const Glyph *g=find_glyph(row->points[i]);
        if(g->page!=page) {
            if(page!=UINT32_MAX) end();
            page=g->page;glBindTexture(GL_TEXTURE_2D,textures[page]);begin();
        }
        float left=cursor+g->bearing_x*scale,top=baseline+g->bearing_y*scale;
        float r=left+g->width*scale,bottom=top+g->height*scale;
        float u=(float)g->x/page_size,v=(float)g->y/page_size;
        float u2=(float)(g->x+g->width)/page_size,v2=(float)(g->y+g->height)/page_size;
        if(max_width>=0 && left>=x+max_width) break;
        if(max_width>=0 && r>x+max_width) {u2=u+(u2-u)*(x+max_width-left)/(r-left);r=x+max_width;}
        uv(u,v);vertex(left,top);uv(u,v2);vertex(left,bottom);
        uv(u2,v2);vertex(r,bottom);uv(u2,v);vertex(r,top);
        cursor+=g->advance_64*(scale/64.f);
    }
    if(page!=UINT32_MAX) end();
    glBindTexture(GL_TEXTURE_2D,bound);active_texture(active);
    if(batched) begin();
    float drawn=text_width(row,scale);
    if(max_width>=0 && drawn>max_width) drawn=max_width;
    *right=x+(float)(int)(drawn+0.5f);
    if(!draw_logged) {write_log("Unicode label submitted: xy=%.1f,%.1f scale=%.3f width=%.1f text=%s; visual confirmation required.",x,y,scale,*right-x,row->source);draw_logged=TRUE;}
    return TRUE;
}
BOOL zh_draw(const char *source,float x,float y,BOOL batched,float *right) {
    return draw_row(lookup(source),x,y,batched,-1,right);
}
BOOL zh_draw_clipped(const char *source,float x,float y,float width,BOOL centered,float *right) {
    const Translation *row=lookup(source);
    float scale=scale_for(*(void**)(image_base+0x496650));
    if(!row || !scale || width<0) return FALSE;
    float length=text_width(row,scale);if(length<0) return FALSE;
    if(centered && length<width) {float offset=(float)(int)((width-length)*0.5f+0.5f);x+=offset;width-=offset;}
    return draw_row(row,x,y,centered,width,right);
}

// Verified 0.9.5.2 TTextRenderer offsets. One layout is shared by measuring and drawing.
typedef struct {
    void *vmt; int x,y,width,height,reserved,left,align,padding;
    void *font; int leading; unsigned char format,pad[3]; float italic;
} TextRenderer;
_Static_assert(offsetof(TextRenderer,font)==0x28,"renderer font offset");
_Static_assert(offsetof(TextRenderer,italic)==0x38,"renderer italic offset");
typedef struct {uint32_t cp;uint64_t color;float advance;int align;BOOL italic;} Atom;
typedef struct {size_t first,end;float width;int align;} TextLine;
typedef struct {Atom *atoms;TextLine *lines;size_t count,line_count;float scale;int leading;BOOL final_lf;} Layout;
static void free_layout(Layout *p) {free(p->atoms);free(p->lines);memset(p,0,sizeof(*p));}
static int hex_digit(char c) {
    if(c>='0' && c<='9') return c-'0';
    if(c>='a' && c<='f') return c-'a'+10;
    if(c>='A' && c<='F') return c-'A'+10;
    return -1;
}
static BOOL closes_line(uint32_t cp) {
    return cp==0x3002 || cp==0xff0c || cp==0xff1a || cp==0xff1b || cp==0xff01 || cp==0xff1f ||
        cp==0x3001 || cp==0x201d || cp==0x2019 || cp==0xff09 || cp==0x300b || cp==')' || cp==']';
}
static BOOL opens_line(uint32_t cp) {return cp==0x201c || cp==0x2018 || cp==0xff08 || cp==0x300a || cp=='(' || cp=='[';}
static BOOL make_layout(TextRenderer *r,const Translation *row,Layout *p) {
    memset(p,0,sizeof(*p));
    if(!r || !row || texture_failure || r->width<=0 || r->width>100000) return FALSE;
    p->scale=scale_for(r->font);
    if(!p->scale) return FALSE;
    p->leading=r->leading?r->leading:((int*)r->font)[7];
    if(!p->scale || p->leading<=0 || p->leading>1024) return FALSE;
    p->atoms=calloc(row->count*4+64,sizeof(Atom));p->lines=calloc(row->count*4+66,sizeof(TextLine));
    if(!p->atoms || !p->lines) {free_layout(p);return FALSE;}
    // Zero is the GUI colour; explicit colours use the high byte as a presence flag.
    uint64_t colors[32]={0};int depth=0,align=0;BOOL italic=FALSE;
    for(size_t i=0;i<row->count;i++) {
        uint32_t cp=row->points[i];
        if(cp=='[') {
            if(!r->format) goto invalid;
            char tag[48];size_t n=0;
            for(i++;i<row->count && row->points[i]!=']';i++) {
                if(row->points[i]>127 || n>=sizeof(tag)-1) goto invalid;
                tag[n++]=(char)row->points[i];
            }
            if(i==row->count) goto invalid;tag[n]=0;
            if(!strncmp(tag,"tcol=",5) && (n==11 || n==13)) {
                if(depth==31) goto invalid;uint32_t value=0;
                for(size_t j=5;j<n;j++) {int d=hex_digit(tag[j]);if(d<0) goto invalid;value=(value<<4)|(uint32_t)d;}
                colors[++depth]=n==11?(0x200000000ULL|((uint64_t)value<<8)):0x100000000ULL|value;
            } else if(!strcmp(tag,"/tcol")) {if(!depth) goto invalid;depth--;}
            else if(!strncmp(tag,"algn=",5) && n==6 && tag[5]>='0' && tag[5]<='2') align=tag[5]-'0';
            else if(!strcmp(tag,"scrp=i")) italic=TRUE;
            else if(!strcmp(tag,"scrp=n")) italic=FALSE;
            else if(!strncmp(tag,"rimg=",5) && n>5) {
                // The game renderer draws the tutorial image. Reserve its
                // 324 px block here so translated paragraphs do not overlap it.
                for(int j=0;j<9;j++) p->atoms[p->count++]=(Atom){'\n',0,0,align,italic};
            }
            else if(!strncmp(tag,"inpt",4)) {
                const char *key=!strcmp(tag,"inpt4")?"Shift":!strcmp(tag,"inpt9")?"Tab":
                    !strcmp(tag,"inpt10")?"I":!strcmp(tag,"inpt11")?"K":
                    !strcmp(tag,"inpt13")?"Alt":!strcmp(tag,"inpt14")?"R":
                    !strcmp(tag,"inpt16")?"C":!strcmp(tag,"inpt17")?"P":NULL;
                if(!key) goto invalid;
                while(*key) {const Glyph *g=find_glyph((unsigned char)*key);
                    if(!g) goto invalid;p->atoms[p->count++]=(Atom){(unsigned char)*key++,colors[depth],g->advance_64*p->scale/64.f,align,italic};}
            }
            else goto invalid;
            continue;
        }
        if(cp=='\r') {if(i+1<row->count && row->points[i+1]=='\n') i++;cp='\n';}
        if(cp=='\t') {
            const Glyph *space=find_glyph(' ');if(!space) goto invalid;
            for(int j=0;j<4;j++) p->atoms[p->count++]=(Atom){' ',colors[depth],space->advance_64*p->scale/64.f,align,italic};
            continue;
        }
        const Glyph *g=find_glyph(cp);
        if(cp!='\n' && !g) goto invalid;
        p->atoms[p->count++]=(Atom){cp,colors[depth],g?g->advance_64*p->scale/64.f:0,align,italic};
    }
    if(depth) goto invalid;
    p->final_lf=row->count && row->points[row->count-1]=='\n';
    for(size_t first=0;first<p->count;) {
        size_t end=first,last_space=SIZE_MAX;float width=0;
        while(end<p->count && p->atoms[end].cp!='\n') {
            float next=width+p->atoms[end].advance;
            if(next>r->width && end>first) break;
            width=next;if(p->atoms[end].cp==' ') last_space=end;
            end++;
        }
        if(end<p->count && p->atoms[end].cp!='\n' && end>first+1) {
            // Prefer word boundaries for embedded Latin text; Chinese breaks between glyphs.
            if(p->atoms[end].cp<128 && p->atoms[end-1].cp<128 && last_space!=SIZE_MAX && last_space>first) end=last_space+1;
            else if(closes_line(p->atoms[end].cp) || opens_line(p->atoms[end-1].cp)) end--;
        }
        width=0;for(size_t j=first;j<end;j++) width+=p->atoms[j].advance;
        p->lines[p->line_count++]=(TextLine){first,end,width,p->atoms[first].align};
        first=end;
        if(first<p->count && p->atoms[first].cp=='\n') first++;
    }
    return TRUE;
invalid:
    free_layout(p);return FALSE;
}
BOOL zh_measure_text(void *renderer,const char *source,int x,int y) {
    TextRenderer *r=renderer;Layout p;
    if(!make_layout(r,lookup(source),&p)) return FALSE;
    r->leading=p.leading;r->x=x;r->y=y+(int)(p.line_count+p.final_lf)*p.leading;
    free_layout(&p);return TRUE;
}
static BOOL draw_paragraph(void *renderer,const Translation *row,float x,float y,int skip,BOOL centered,BOOL raw,int *consumed) {
    if(!image_base || skip<0) return FALSE;
    TextRenderer *r=renderer;Layout p;
    if(!make_layout(r,row,&p)) return FALSE;
    if(!upload_textures()) {free_layout(&p);return FALSE;}
    void (*begin)(void)=(void*)(image_base+0x1f6c00);
    void (*end)(void)=(void*)(image_base+0x1f6f10);
    void (*uv)(float,float)=(void*)(image_base+0x1f6de0);
    void (*vertex)(float,float)=(void*)(image_base+0x1f6ca0);
    void (*color)(void*)=(void*)(image_base+0x1f6e60);
    unsigned char *gui=*(unsigned char**)(image_base+0x5ae0d0);
    unsigned char original_color[4];memcpy(original_color,raw?image_base+0x5aad00:gui+0xe4,4);
    GLint active,bound;glGetIntegerv(0x84e0,&active);active_texture(0x84c0);glGetIntegerv(GL_TEXTURE_BINDING_2D,&bound);
    // Both paragraph entry points own their batch, just like the original
    // renderer. Engine End leaves its vertex count intact; it is not a
    // pending-work flag. Flushing here replays the previous image/text with
    // the current texture and transform (duplicate icons and garbage glyphs).
    // The first begin() below discards that already-submitted geometry.
    uint32_t page=UINT32_MAX;unsigned batch_count=0;int drawn=0;
    r->leading=p.leading;r->left=x;r->align=0;r->x=x;r->y=y;r->italic=0;
    for(size_t k=(size_t)skip;k<p.line_count;k++) {
        if((drawn+1)*p.leading>r->height) break;
        TextLine *line=p.lines+k;float cursor=(float)x;
        if(centered) line->align=2;
        if(line->align==1) cursor+=r->width-line->width;
        if(line->align==2) cursor+=(r->width-line->width)*0.5f;
        float baseline=y+drawn*p.leading+((int*)r->font)[3]-4.f*p.scale;
        for(size_t j=line->first;j<line->end;j++) {
            Atom *a=p.atoms+j;const Glyph *g=find_glyph(a->cp);
            if(page!=g->page || batch_count>=512) {
                if(page!=UINT32_MAX) end();page=g->page;
                glBindTexture(GL_TEXTURE_2D,textures[page]);begin();batch_count=0;
            }
            unsigned char rgba[4];memcpy(rgba,original_color,4);
            if(a->color) {
                rgba[0]=(a->color>>24)&255;rgba[1]=(a->color>>16)&255;rgba[2]=(a->color>>8)&255;
                if(a->color&0x100000000ULL) rgba[3]=(unsigned char)(original_color[3]*(a->color&255)/255);
            }
            color(rgba);
            float left=cursor+g->bearing_x*p.scale,top=baseline+g->bearing_y*p.scale;
            float right=left+g->width*p.scale,bottom=top+g->height*p.scale;
            float lean=a->italic?g->height*p.scale*0.15f:0;
            float u=(float)g->x/page_size,v=(float)g->y/page_size,u2=(float)(g->x+g->width)/page_size,v2=(float)(g->y+g->height)/page_size;
            uv(u,v);vertex(left+lean,top);uv(u,v2);vertex(left,bottom);
            uv(u2,v2);vertex(right,bottom);uv(u2,v);vertex(right+lean,top);
            cursor+=a->advance;batch_count++;
        }
        r->x=(int)(cursor+0.5f);r->align=line->align;drawn++;
    }
    r->y=y+drawn*p.leading;
    if(consumed) *consumed=r->height<p.leading?0:(int)((size_t)(skip+drawn)<p.line_count?(size_t)(skip+drawn):p.line_count);
    if(page!=UINT32_MAX) end();
    glBindTexture(GL_TEXTURE_2D,bound);active_texture(active);color(original_color);
    static BOOL logged;if(!logged) {write_log("Unicode paragraph submitted: %zu lines, %d visible; visual confirmation required.",p.line_count,drawn);logged=TRUE;}
    free_layout(&p);return TRUE;
}
BOOL zh_draw_text(void *renderer,const char *source,int x,int y,int skip,const void *selection) {
    // Editable selections address original bytes and need a separate index mapping.
    if(selection) {const int *s=selection;if(s[0]!=s[1]) return FALSE;}
    return draw_paragraph(renderer,lookup(source),(float)x,(float)y,skip,FALSE,FALSE,NULL);
}
int zh_draw_block(const char *source,int length,float x,float y,int width,int height,int skip,BOOL centered) {
    if(!image_base) return -1;
    TextRenderer r={.font=*(void**)(image_base+0x496650),.width=width,.height=height};int lines;
    return draw_paragraph(&r,lookup_span(source,length),x,y,skip,centered,TRUE,&lines)?lines:-1;
}
int zh_block_lines(const char *source,int length,int width,void *font) {
    TextRenderer r={.font=font,.width=width};Layout p;
    if(!make_layout(&r,lookup_span(source,length),&p)) return -1;
    int lines=(int)p.line_count;free_layout(&p);return lines;
}
