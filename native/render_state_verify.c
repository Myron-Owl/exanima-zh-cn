// Exercise the actual Unicode draw paths against the verified engine batch contract.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
static GLint bound_texture=77,active_unit=0x84c0;
static HGLRC WINAPI test_context(void) {return (HGLRC)(uintptr_t)1;}
static void APIENTRY test_get(GLenum key,GLint *out) {*out=key==0x84e0?active_unit:bound_texture;}
static void APIENTRY test_bind(GLenum target,GLuint texture) {(void)target;bound_texture=(GLint)texture;}
static void APIENTRY test_active(GLenum unit) {active_unit=(GLint)unit;}
#define wglGetCurrentContext test_context
#define glGetIntegerv test_get
#define glBindTexture test_bind
#define ZH_VERIFY
#include "unicode.c"
#include "version_profiles.h"
#include "compatibility.h"
static int ends,stale_draws,vertices;
static ZhEngineLayout test_layout;
static void report(const char *format,...) {(void)format;}
static void mock_begin(void) {*(int*)(image_base+test_layout.batch_count)=0;}
static void mock_end(void) {
    ends++;
    if(bound_texture==77 && *(int*)(image_base+test_layout.batch_count)>0) stale_draws++;
    // Verified engine End submits without clearing the vertex count.
}
static void mock_uv(float u,float v) {(void)u;(void)v;}
static void mock_vertex(float x,float y) {(void)x;(void)y;vertices++;(*(int*)(image_base+test_layout.batch_count))++;}
static void mock_color(void *rgba) {memcpy(image_base+test_layout.current_color,rgba,4);}
static void thunk(unsigned char *at,void *fn) {
    unsigned char code[14]={0xff,0x25,0,0,0,0};memcpy(code+6,&fn,8);memcpy(at,code,sizeof(code));
}
static void reset_stale(void) {ends=stale_draws=vertices=0;bound_texture=77;active_unit=0x84c1;*(int*)(image_base+test_layout.batch_count)=8;}
static char *place_text(unsigned char *memory,uint32_t rva,const char *text) {
    int64_t refs=-1,length=(int64_t)strlen(text);
    memcpy(memory+rva-16,&refs,8);memcpy(memory+rva-8,&length,8);
    strcpy((char*)memory+rva,text);return (char*)memory+rva;
}
static int scope_test(unsigned char *memory,const char *mode) {
    ZhScopeRva scopes[]={{0x123450,0x234560},{0x123490,0x2345a0}};
    BOOL legacy=!strcmp(mode,"legacy");
    BOOL reject=!strcmp(mode,"missing") || !strcmp(mode,"duplicate") || !strcmp(mode,"collision");
    if(!legacy && !reject && strcmp(mode,"mapped")) return 40;
    if(!legacy) {
        test_layout.scopes=scopes;test_layout.scope_count=2;test_layout.remap_scopes=TRUE;
        if(!strcmp(mode,"missing")) test_layout.scope_count=1;
        if(!strcmp(mode,"duplicate")) scopes[1].legacy_rva=scopes[0].legacy_rva;
        if(!strcmp(mode,"collision")) scopes[1].current_rva=scopes[0].current_rva;
        zh_set_layout(&test_layout);
    }
    BOOL loaded=zh_load(GetModuleHandleW(NULL),memory,report);
    if(reject) {
        if(loaded || dictionary_count || lookup_exact_span("zh.test.scope.only",18)) return 41;
        printf("SCOPE_REJECTED mode=%s dictionary_count=%zu\n",mode,dictionary_count);return 0;
    }
    if(!loaded) return 42;
    uint32_t first=legacy?scopes[0].legacy_rva:scopes[0].current_rva;
    uint32_t second=legacy?scopes[1].legacy_rva:scopes[1].current_rva;
    char *source=place_text(memory,first,"zh.test.scope.only");
    const Translation *matched=lookup(source);
    if(!matched || matched->source_rva!=first || !zh_has_translation(source)) return 43;
    struct {int64_t refs,length;char source[64];} wrong={-1,0,"zh.test.scope.only"};
    wrong.length=(int64_t)strlen(wrong.source);
    if(zh_has_translation(wrong.source) || lookup(wrong.source)) return 44;
    if(!legacy) {
        char *old=place_text(memory,scopes[0].legacy_rva,"zh.test.scope.only");
        if(zh_has_translation(old)) return 45;
    }
    source=place_text(memory,second,"zh.test.scope.fallback");matched=lookup(source);
    if(!matched || matched->source_rva!=second) return 46;
    strcpy(wrong.source,"zh.test.scope.fallback");wrong.length=(int64_t)strlen(wrong.source);
    const Translation *fallback=lookup(wrong.source);
    if(!fallback || fallback->source_rva || fallback==matched) return 47;
    if(matched->count==fallback->count && !memcmp(matched->points,fallback->points,matched->count*sizeof(uint32_t))) return 48;
    ZhEngineLayout late={0};zh_set_layout(&late);
    if(engine_layout.font_slot!=test_layout.font_slot) return 49;
    printf("SCOPE_MATCH_CHECKS_PASSED mode=%s scoped_rva=%x wrong_pointer_refused=1 unscoped_fallback_preserved=1\n",mode,first);
    return 0;
}
static int profile_dictionary_test(unsigned char *memory,const char *path,const ZhGameVersion *profile) {
    FILE *file=fopen(path,"rb");if(!file) return 60;
    char magic[4];uint32_t count;
    if(fread(magic,1,4,file)!=4 || memcmp(magic,"ZPV1",4) || fread(&count,4,1,file)!=1 || count>20000) {fclose(file);return 61;}
    uint32_t expected_layout[9];
    const uint32_t actual_layout[]={test_layout.font_slot,test_layout.begin,test_layout.end,test_layout.uv,
        test_layout.vertex,test_layout.color,test_layout.batch_count,test_layout.gui_slot,test_layout.current_color};
    if(fread(expected_layout,4,9,file)!=9 || memcmp(expected_layout,actual_layout,sizeof(actual_layout))) {fclose(file);return 72;}
    char *actual=malloc(262145);if(!actual) {fclose(file);return 62;}
    size_t dictionary_cases=0,scope_rows=0,wrong_pointers=0,old_pointers=0,layouts=0;
    int font[8]={0};font[3]=36;font[4]=30;font[7]=36;
    for(uint32_t i=0;i<count;i++) {
        uint32_t fields[5];
        if(fread(fields,4,5,file)!=5 || fields[1]>65536 || fields[2]>262144 || fields[4]>2) return 63;
        uint32_t rva=fields[0],source_length=fields[1],expected_length=fields[2],expected_scope=fields[3],kind=fields[4];
        char *storage=malloc(16+(size_t)source_length+1),*expected=malloc((size_t)expected_length+1);
        if(!storage || !expected) return 64;
        char *source=storage+16;
        if(fread(source,1,source_length,file)!=source_length || fread(expected,1,expected_length,file)!=expected_length) return 65;
        source[source_length]=0;expected[expected_length]=0;
        int64_t refs=-1,length=source_length;memcpy(storage,&refs,8);memcpy(storage+8,&length,8);
        if(rva) {
            if(rva<16 || rva>=0x600000-source_length) return 66;
            memcpy(memory+rva-16,storage,16+(size_t)source_length+1);source=(char*)memory+rva;
        }
        int n=zh_test_translate(source,(int)source_length,actual,262144);
        const Translation *matched=lookup_span(source,source_length);
        if((!expected_length && (n!=-1 || matched)) ||
           (expected_length && (n!=(int)expected_length || memcmp(actual,expected,expected_length) || !matched || matched->source_rva!=expected_scope))) {
            printf("PROFILE_DICTIONARY_FAIL profile=%s case=%u kind=%u rva=%x expected_scope=%x actual_scope=%x result=%d source=%s\n",
                profile->id,i,kind,rva,expected_scope,matched?matched->source_rva:0,n,source);return 67;
        }
        if(kind==0) {dictionary_cases++;if(expected_scope) scope_rows++;}
        else if(kind==1) wrong_pointers++;
        else old_pointers++;
        if(expected_length && source[0]!='@' && !strstr(source,"{Actor[")) {
            TextRenderer r={.font=font,.height=100000,.format=1};
            for(int width=320;width<=960;width+=320) {
                r.width=width;r.x=123;r.y=456;
                if(!zh_measure_text(&r,source,0,0) || r.y<=0) {
                    printf("PROFILE_LAYOUT_FAIL profile=%s case=%u width=%d source=%s\n",profile->id,i,width,source);return 68;
                }
                layouts++;
            }
        }
        free(storage);free(expected);
    }
    if(fgetc(file)!=EOF) return 69;
    free(actual);fclose(file);
    printf("PROFILE_DICTIONARY_CHECKS_PASSED profile=%s layout_fields=9 dictionary=%zu scoped=%zu wrong_pointer=%zu old_rva=%zu layouts=%zu\n",
        profile->id,dictionary_cases,scope_rows,wrong_pointers,old_pointers,layouts);
    return 0;
}
int main(int argc,char **argv) {
    uint32_t shift=0;const char *scope_mode=NULL,*profile_hash=NULL,*fixtures=NULL,*auto_file=NULL,*metadata_file=NULL;BOOL expect_unknown=FALSE;
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--shift") && i+1<argc) {
            char *end;unsigned long value=strtoul(argv[++i],&end,0);
            if(*end || value>0x100000 || value%0x10000) return 50;
            shift=(uint32_t)value;
        } else if(!strcmp(argv[i],"--scope-test") && i+1<argc) scope_mode=argv[++i];
        else if(!strcmp(argv[i],"--profile") && i+1<argc) profile_hash=argv[++i];
        else if(!strcmp(argv[i],"--cases") && i+1<argc) fixtures=argv[++i];
        else if(!strcmp(argv[i],"--expect-unknown")) expect_unknown=TRUE;
        else if(!strcmp(argv[i],"--auto-file") && i+1<argc) auto_file=argv[++i];
        else if(!strcmp(argv[i],"--metadata") && i+1<argc) metadata_file=argv[++i];
        else return 51;
    }
    const ZhGameVersion *profile=profile_hash?zh_find_version(profile_hash):NULL;
    ZhCompatResult detected;
    if(auto_file) {
        if(profile_hash || !metadata_file || !fixtures || shift || scope_mode || expect_unknown) return 73;
        wchar_t executable[MAX_PATH],metadata[MAX_PATH];
        if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,auto_file,-1,executable,MAX_PATH) ||
           !MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,metadata_file,-1,metadata,MAX_PATH)) return 74;
        unsigned char *exe=NULL,*config=NULL;size_t exe_size=0,config_size=0;char reason[256];
        if(!zh_read_file(executable,64*1024*1024,&exe,&exe_size) || !zh_read_file(metadata,2*1024*1024,&config,&config_size) ||
           !zh_auto_detect(exe,exe_size,config,config_size,&detected,reason,sizeof(reason))) return 75;
        HeapFree(GetProcessHeap(),0,exe);HeapFree(GetProcessHeap(),0,config);profile=&detected.version;
        printf("AUTOMATIC_LAYOUT_SELECTED functions=%u\n",detected.function_count);
    }
    if(expect_unknown) {
        if(!profile_hash || profile || layout_locked || dictionary_count || image_base) return 70;
        puts("UNKNOWN_SHA_REJECTED_BEFORE_ASSET_LOAD");return 0;
    }
    if((profile_hash && !profile) || (profile && (shift || scope_mode || !fixtures)) || (fixtures && !profile)) return 71;
    test_layout=engine_layout;
    unsigned char *memory=VirtualAlloc(NULL,0x600000+shift,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    if(!memory) return 2;
    if(scope_mode) return scope_test(memory,scope_mode);
    uint32_t *fields[]={&test_layout.font_slot,&test_layout.begin,&test_layout.end,&test_layout.uv,
        &test_layout.vertex,&test_layout.color,&test_layout.batch_count,&test_layout.gui_slot,&test_layout.current_color};
    uint32_t old[9];for(size_t i=0;i<9;i++) old[i]=*fields[i];
    if(profile) test_layout=profile->layout;
    else for(size_t i=0;i<9;i++) *fields[i]+=shift;
    if(shift || profile) zh_set_layout(&test_layout);
    if(!memory || !zh_load(GetModuleHandleW(NULL),memory,report)) return 2;
    ZhEngineLayout late={0};zh_set_layout(&late);
    if(engine_layout.font_slot!=test_layout.font_slot) return 52;
    if(profile) {int result=profile_dictionary_test(memory,fixtures,profile);if(result) return result;}
    BOOL relocated=FALSE;
    for(size_t i=0;i<9;i++) if(*fields[i]!=old[i]) {
        relocated=TRUE;
        uint32_t page=old[i]&~0xfffU;
        for(size_t j=0;j<9;j++) if((*fields[j]&~0xfffU)==page) return 53;
        DWORD previous;if(!VirtualProtect(memory+page,0x1000,PAGE_NOACCESS,&previous)) return 54;
    }
    thunk(memory+test_layout.begin,mock_begin);thunk(memory+test_layout.end,mock_end);
    thunk(memory+test_layout.uv,mock_uv);thunk(memory+test_layout.vertex,mock_vertex);thunk(memory+test_layout.color,mock_color);
    if(!FlushInstructionCache(GetCurrentProcess(),memory+test_layout.begin,0x1000)) return 55;
    int font[8]={0};font[3]=36;font[4]=30;font[7]=36;
    *(void**)(memory+test_layout.font_slot)=font;*(void**)(memory+test_layout.gui_slot)=memory+0x8000;
    const unsigned char gui_color[4]={101,111,121,131},raw_color[4]={17,34,51,68};
    memcpy(memory+0x80e4,gui_color,4);memcpy(memory+test_layout.current_color,raw_color,4);
    texture_context=(HGLRC)(uintptr_t)1;active_texture=test_active;textures[0]=99;
    struct {int64_t refs,length;char source[32];} text={-1,14,"Audio volume: "};
    TextRenderer r={.font=font,.width=700,.height=300,.format=1};
    reset_stale();
    if(!zh_draw_text(&r,text.source,8,0,0,NULL)) return 3;
    printf("RICH_PARAGRAPH stale=%d submits=%d vertices=%d\n",stale_draws,ends,vertices);
    if(stale_draws || ends!=1 || vertices<=0 || bound_texture!=77 || active_unit!=0x84c1 ||
       memcmp(memory+test_layout.current_color,gui_color,4)) return 10;
    memcpy(memory+test_layout.current_color,raw_color,4);
    reset_stale();
    if(zh_draw_block(text.source,14,8,0,700,300,0,FALSE)<0) return 4;
    printf("RAW_PARAGRAPH stale=%d submits=%d vertices=%d\n",stale_draws,ends,vertices);
    if(stale_draws || ends!=1 || vertices<=0 || bound_texture!=77 || active_unit!=0x84c1 ||
       memcmp(memory+test_layout.current_color,raw_color,4)) return 11;
    reset_stale();float right;
    if(!zh_draw(text.source,8,36,TRUE,&right)) return 5;
    printf("BATCH_LABEL pending_submits=%d total_submits=%d remaining_vertices=%d\n",stale_draws,ends,*(int*)(memory+test_layout.batch_count));
    if(stale_draws!=1 || ends!=2 || *(int*)(memory+test_layout.batch_count)!=0 || bound_texture!=77 || active_unit!=0x84c1) return 12;
    reset_stale();
    if(!zh_draw_clipped(text.source,8,36,700,TRUE,&right)) return 13;
    if(stale_draws!=1 || ends!=2 || vertices<=0 || *(int*)(memory+test_layout.batch_count)!=0 || bound_texture!=77 || active_unit!=0x84c1) return 14;
    printf("CLIPPED_CENTERED_LABEL shift=%x profile=%s old_pages_protected=%d vertices=%d\n",shift,profile?profile->id:"default",relocated?1:0,vertices);
    puts("RENDER_BATCH_OWNERSHIP_CHECKS_PASSED");return 0;
}
