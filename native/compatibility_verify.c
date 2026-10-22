#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "compatibility.h"
static uint32_t get32(const unsigned char *p) {uint32_t value;memcpy(&value,p,4);return value;}
static BOOL mapped_test(const unsigned char *file,size_t size,const ZhCompatResult *result) {
    (void)size;
    uint32_t nt=get32(file+0x3c),opt=nt+24,image_size=get32(file+opt+56);
    uint16_t count,optional_size;memcpy(&count,file+nt+6,2);memcpy(&optional_size,file+nt+20,2);
    unsigned char *base=VirtualAlloc(NULL,image_size,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);if(!base) return FALSE;
    for(uint16_t n=0;n<count;n++) {
        const unsigned char *s=file+opt+optional_size+n*40;uint32_t rva=get32(s+12),raw_size=get32(s+16),raw=get32(s+20);
        if(raw_size) memcpy(base+rva,file+raw,raw_size);
    }
    for(unsigned n=0;n<9;n++) if(result->scope_slots[n]) {
        uintptr_t address=(uintptr_t)(base+result->scopes[n].current_rva);memcpy(base+result->scope_slots[n],&address,8);
    }
    char reason[256];BOOL ok=zh_auto_verify_loaded(file,size,base,result,reason,sizeof(reason));
    uint32_t function=result->function_rvas[0];base[function]^=1;
    ok=ok && !zh_auto_verify_loaded(file,size,base,result,reason,sizeof(reason));base[function]^=1;
    uint32_t text=result->scopes[0].current_rva;base[text]^=1;
    ok=ok && !zh_auto_verify_loaded(file,size,base,result,reason,sizeof(reason));base[text]^=1;
    uint32_t slot=result->scope_slots[0];base[slot]^=1;
    ok=ok && !zh_auto_verify_loaded(file,size,base,result,reason,sizeof(reason));
    VirtualFree(base,0,MEM_RELEASE);return ok;
}
int wmain(int argc,wchar_t **argv) {
    if(argc!=3 && (argc!=4 || wcscmp(argv[3],L"--mapped-test"))) {fprintf(stderr,"Usage: compatibility_verify EXE compatibility.zhc [--mapped-test]\n");return 2;}
    unsigned char *exe=NULL,*metadata=NULL;size_t exe_size=0,metadata_size=0;char reason[256]={0};
    ZhCompatResult result;
    if(!zh_read_file(argv[1],64*1024*1024,&exe,&exe_size) || !zh_read_file(argv[2],2*1024*1024,&metadata,&metadata_size)) {
        printf("{\"compatible\":false,\"reason\":\"input unavailable\"}\n");return 1;
    }
    BOOL ok=zh_auto_detect(exe,exe_size,metadata,metadata_size,&result,reason,sizeof(reason));
    if(ok && argc==4 && !mapped_test(exe,exe_size,&result)) {ok=FALSE;snprintf(reason,sizeof(reason),"loaded-memory regression failed");}
    if(ok) {
        const ZhEngineLayout *p=&result.version.layout;
        printf("{\"compatible\":true,\"function_count\":%u,\"hooks\":[",result.function_count);
        for(unsigned i=0;i<11;i++) printf("%s%u",i?",":"",result.version.hooks[i].rva);
        printf("],\"layout\":[%u,%u,%u,%u,%u,%u,%u,%u,%u],\"scopes\":[",p->font_slot,p->begin,p->end,p->uv,p->vertex,p->color,p->batch_count,p->gui_slot,p->current_color);
        for(unsigned i=0;i<9;i++) printf("%s[%u,%u]",i?",":"",result.scopes[i].legacy_rva,result.scopes[i].current_rva);
        printf("]}\n");
    } else printf("{\"compatible\":false,\"reason\":\"%s\"}\n",reason);
    HeapFree(GetProcessHeap(),0,exe);HeapFree(GetProcessHeap(),0,metadata);return ok?0:1;
}
