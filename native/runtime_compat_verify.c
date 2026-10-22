/* Exercise the real initialization transaction against an owned mapped PE fixture. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
static wchar_t fixture_path[MAX_PATH];
static unsigned char *fixture_base;
static DWORD test_filename(HMODULE module,wchar_t *path,DWORD capacity) {
    if(module) return GetModuleFileNameW(NULL,path,capacity);
    size_t size=wcslen(fixture_path);
    if(size>=capacity) return 0;
    memcpy(path,fixture_path,(size+1)*sizeof(wchar_t));return (DWORD)size;
}
static HMODULE test_module(const wchar_t *name) {return name?GetModuleHandleW(name):(HMODULE)fixture_base;}
#define GetModuleFileNameW test_filename
#define GetModuleHandleW test_module
#include "runtime.c"
#undef GetModuleFileNameW
#undef GetModuleHandleW
int zh_test_translate(const char *source,int length,char *out,int capacity);
static uint32_t get32(const unsigned char *p) {uint32_t value;memcpy(&value,p,4);return value;}
int wmain(int argc,wchar_t **argv) {
    if(argc!=3) return 2;
    BOOL expect_success=!wcscmp(argv[2],L"accept"),change_loaded=!wcscmp(argv[2],L"changed-loaded");
    if(!expect_success && !change_loaded && wcscmp(argv[2],L"reject")) return 3;
    if(wcslen(argv[1])>=MAX_PATH) return 4;
    wcscpy(fixture_path,argv[1]);unsigned char *file=NULL;size_t size=0;
    if(!zh_read_file(fixture_path,64*1024*1024,&file,&size) || size<0x300) return 5;
    uint32_t nt=get32(file+0x3c),opt=nt+24,image_size=get32(file+opt+56);uint64_t preferred;
    uint16_t count,optional_size;memcpy(&count,file+nt+6,2);memcpy(&optional_size,file+nt+20,2);memcpy(&preferred,file+opt+24,8);
    fixture_base=VirtualAlloc(NULL,image_size,MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    unsigned char *before=HeapAlloc(GetProcessHeap(),0,image_size);if(!fixture_base || !before) return 6;
    for(uint16_t n=0;n<count;n++) {
        const unsigned char *s=file+opt+optional_size+n*40;uint32_t rva=get32(s+12),raw_size=get32(s+16),raw=get32(s+20),flags=get32(s+36);
        if(raw_size) memcpy(fixture_base+rva,file+raw,raw_size);
        if(!(flags&0x20000000)) for(uint32_t pos=0;pos+8<=raw_size;pos+=8) {
            uint64_t value;memcpy(&value,fixture_base+rva+pos,8);
            if(value>=preferred && value-preferred<image_size) {
                value=(uintptr_t)fixture_base+value-preferred;memcpy(fixture_base+rva+pos,&value,8);
            }
        }
    }
    if(change_loaded) fixture_base[0x1100+24]^=1;
    memcpy(before,fixture_base,image_size);
    DllMain(GetModuleHandleW(NULL),DLL_PROCESS_ATTACH,NULL);
    BOOL initialized_ok=ExanimaZhInitialize();
    BOOL text_unchanged=!memcmp(before,fixture_base,image_size);
    BOOL hooks=TRUE;
    if(initialized_ok) {
        if(version!=&auto_version.version || auto_version.function_count!=22) return 7;
        for(unsigned n=0;n<11;n++) {
            const unsigned char *at=fixture_base+version->hooks[n].rva;
            if(at[0]!=0xff || at[1]!=0x25) hooks=FALSE;
        }
        const char *back=(const char*)fixture_base+version->layout.scopes[0].current_rva;
        char output[256];
        if(zh_test_translate(back,4,output,sizeof(output))!=6 || memcmp(output,"\xe5\x90\x8e\xe9\x80\x80",6)) return 8;
        struct {int64_t refs,length;char text[128];} future={-1,0,"Future content that is absent from the localization dictionary."};
        future.length=(int64_t)strlen(future.text);
        if(zh_test_translate(future.text,(int)future.length,output,sizeof(output))!=-1) return 9;
    }
    BOOL passed=expect_success?(initialized_ok && hooks && !text_unchanged):(!initialized_ok && text_unchanged);
    printf("{\"passed\":%s,\"initialized\":%s,\"text_unchanged\":%s,\"automatic_profile\":%s,\"future_english_fallback\":%s}\n",
           passed?"true":"false",initialized_ok?"true":"false",text_unchanged?"true":"false",
           initialized_ok?"true":"false",initialized_ok?"true":"false");
    return passed?0:1;
}
