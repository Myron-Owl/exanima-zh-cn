#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <wchar.h>
#include "unicode.h"

static HMODULE self;
static unsigned char *base;
static HANDLE logfile = INVALID_HANDLE_VALUE;
static SRWLOCK log_lock = SRWLOCK_INIT;
static LONG initialized;
static void log_line(const char *format, ...) {
    if (logfile == INVALID_HANDLE_VALUE) return;
    char line[2048]; va_list args; va_start(args,format);
    int n = vsnprintf(line,sizeof(line)-3,format,args); va_end(args);
    if(n<0) return; if(n>(int)sizeof(line)-3) n=sizeof(line)-3;
    line[n++]='\r'; line[n++]='\n'; DWORD wrote;
    AcquireSRWLockExclusive(&log_lock);
    WriteFile(logfile,line,n,&wrote,NULL); FlushFileBuffers(logfile);
    ReleaseSRWLockExclusive(&log_lock);
}
static BOOL verify_exe(void) {
    wchar_t path[MAX_PATH];
    DWORD length=GetModuleFileNameW(NULL,path,MAX_PATH);
    if(!length || length>=MAX_PATH) return FALSE;
    HANDLE f=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    if(f==INVALID_HANDLE_VALUE) return FALSE;
    BCRYPT_ALG_HANDLE alg=NULL; BCRYPT_HASH_HANDLE hash=NULL;
    unsigned char digest[32],buffer[16384]; DWORD n; BOOL ok=FALSE;
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)<0) goto done;
    if(BCryptCreateHash(alg,&hash,NULL,0,NULL,0,0)<0) goto done;
    for(;;) {
        if(!ReadFile(f,buffer,sizeof(buffer),&n,NULL)) goto done;
        if(!n) break;
        if(BCryptHashData(hash,buffer,n,0)<0) goto done;
    }
    if(BCryptFinishHash(hash,digest,32,0)<0) goto done;
    char hex[65]; for(int i=0;i<32;i++) sprintf(hex+i*2,"%02x",digest[i]);
    log_line("Executable SHA256: %s",hex);
    ok=!strcmp(hex,"97a83509f1e230349126817adb8576a7725bceda120023f1173bb463b46cba6a");
done:
    if(hash) BCryptDestroyHash(hash);
    if(alg) BCryptCloseAlgorithmProvider(alg,0);
    CloseHandle(f); return ok;
}

typedef struct { void *entry; void *replacement; unsigned char signature[24]; size_t size; void *trampoline; } Hook;
static void jump(void *at,void *target) {
    unsigned char data[14]={0xff,0x25,0,0,0,0};
    memcpy(data+6,&target,8); memcpy(at,data,14);
}
// Draw prologues have no relative operands. Width prologues contain only a
// short branch to byte 14, which remains the continuation jump in the copy.
static BOOL prepare_hook(Hook *hook) {
    if(memcmp(hook->entry,hook->signature,hook->size)) return FALSE;
    hook->trampoline=VirtualAlloc(NULL,64,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!hook->trampoline) return FALSE;
    memcpy(hook->trampoline,hook->entry,hook->size);
    jump((char*)hook->trampoline+hook->size,(char*)hook->entry+hook->size);
    DWORD old;
    return VirtualProtect(hook->trampoline,64,PAGE_EXECUTE_READ,&old) &&
        FlushInstructionCache(GetCurrentProcess(),hook->trampoline,64);
}
static BOOL install_hooks(Hook *hooks,size_t count) {
    // Pause existing peer threads, refusing to overwrite an active prologue.
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    if(snapshot==INVALID_HANDLE_VALUE) return FALSE;
    HANDLE threads[256]; size_t used=0; BOOL ok=TRUE;
    THREADENTRY32 te={.dwSize=sizeof(te)};
    if(!Thread32First(snapshot,&te)) ok=FALSE;
    else do {
        if(te.th32OwnerProcessID!=GetCurrentProcessId() || te.th32ThreadID==GetCurrentThreadId()) continue;
        if(used==256) {ok=FALSE;break;}
        HANDLE t=OpenThread(THREAD_SUSPEND_RESUME|THREAD_GET_CONTEXT|THREAD_QUERY_INFORMATION,FALSE,te.th32ThreadID);
        if(!t) {ok=FALSE;break;}
        if(SuspendThread(t)==(DWORD)-1) {CloseHandle(t);ok=FALSE;break;}
        threads[used++]=t;
        CONTEXT ctx={.ContextFlags=CONTEXT_CONTROL};
        if(!GetThreadContext(t,&ctx)) {ok=FALSE;break;}
        for(size_t i=0;i<count;i++) {
            uintptr_t p=(uintptr_t)hooks[i].entry;
            if(ctx.Rip>=p && ctx.Rip<p+hooks[i].size) ok=FALSE;
        }
        if(!ok) break;
    } while(Thread32Next(snapshot,&te));
    DWORD protections[16]; size_t writable=0;
    if(count>16) ok=FALSE;
    if(ok) for(size_t i=0;i<count;i++) {
        if(!VirtualProtect(hooks[i].entry,hooks[i].size,PAGE_EXECUTE_READWRITE,&protections[i])) {ok=FALSE;break;}
        writable++;
    }
    if(ok) for(size_t i=0;i<count;i++) {
        jump(hooks[i].entry,hooks[i].replacement);
        memset((char*)hooks[i].entry+14,0x90,hooks[i].size-14);
        FlushInstructionCache(GetCurrentProcess(),hooks[i].entry,hooks[i].size);
    }
    for(size_t i=0;i<writable;i++) {DWORD unused; VirtualProtect(hooks[i].entry,hooks[i].size,protections[i],&unused);}
    while(used) {HANDLE t=threads[--used];ResumeThread(t);CloseHandle(t);}
    CloseHandle(snapshot); return ok;
}

typedef void (*DrawFn)(void*,const char*,int,int,int,const void*);
typedef void (*MeasureFn)(void*,const char*,int,int);
static DrawFn original_draw;
static MeasureFn original_measure;
typedef int (*BlockFn)(const char*,int,int,int,int,int,int,unsigned char);
typedef void (*FloatBlockFn)(const char*,int,float,float,int,int,int,unsigned char);
typedef int (*BlockLinesFn)(const char*,int,int,void*);
static BlockFn original_block;
static FloatBlockFn original_float_block;
static BlockLinesFn original_block_lines;
typedef float (*LabelFn)(float,float,const char*);
typedef float (*CenteredFn)(float,float,float,const char*);
typedef void (*ClippedFn)(float,float,float,const char*);
typedef int (*WidthFn)(const char*);
typedef int (*FontWidthFn)(const char*,void*);
static LabelFn original_label,original_batch;
static CenteredFn original_center;
static ClippedFn original_clip;
static WidthFn original_width;
static FontWidthFn original_font_width;
static uint64_t seen[4096];
static size_t seen_count;
static SRWLOCK seen_lock=SRWLOCK_INIT;
static void record(const char *kind,void *renderer,const char *text,int x,int y) {
    if(!text) return;
    int64_t length; memcpy(&length,text-8,8);
    if(length<1 || length>16384) return;
    uint64_t hash=1469598103934665603ULL;
    for(int64_t i=0;i<length;i++) hash=(hash^(unsigned char)text[i])*1099511628211ULL;
    hash^=(unsigned char)kind[0];
    AcquireSRWLockExclusive(&seen_lock);
    for(size_t i=0;i<seen_count;i++) if(seen[i]==hash) {ReleaseSRWLockExclusive(&seen_lock);return;}
    if(seen_count==4096) {ReleaseSRWLockExclusive(&seen_lock);return;}
    seen[seen_count++]=hash;
    ReleaseSRWLockExclusive(&seen_lock);
    void *font=*(void**)(base+0x496650);
    int *f=(int*)font;
    log_line("%s xy=%d,%d renderer=%p font=%p size=%d,%d cap=%d leading=%d text=%.*s",kind,x,y,renderer,font,
        f?f[2]:0,f?f[3]:0,f?f[4]:0,f?f[7]:0,(int)(length<1400?length:1400),text);
}
static void draw_hook(void *r,const char *s,int x,int y,int skip,const void *selection) {
    record("draw",r,s,x,y);
    if(zh_draw_text(r,s,x,y,skip,selection)) return;
    original_draw(r,s,x,y,skip,selection);
}
static void measure_hook(void *r,const char *s,int x,int y) {
    record("measure",r,s,x,y);
    if(!zh_measure_text(r,s,x,y)) original_measure(r,s,x,y);
}
static float label_hook(float x,float y,const char *s) {
    record("label",NULL,s,(int)x,(int)y);float right;
    if(zh_draw(s,x,y,FALSE,&right)) return right;
    return original_label(x,y,s);
}
static float batch_hook(float x,float y,const char *s) {
    record("batch",NULL,s,(int)x,(int)y);float right;
    if(zh_draw(s,x,y,TRUE,&right)) return right;
    return original_batch(x,y,s);
}
static float center_hook(float x,float y,float width,const char *s) {
    record("center",NULL,s,(int)x,(int)y);
    float right;if(zh_draw_clipped(s,x,y,width,TRUE,&right)) return right;
    return original_center(x,y,width,s);
}
static void clip_hook(float x,float y,float width,const char *s) {
    record("truncate",NULL,s,(int)x,(int)y);
    float right;if(zh_draw_clipped(s,x,y,width,FALSE,&right)) return;
    original_clip(x,y,width,s);
}
static int width_hook(const char *s) {
    int width=zh_width(s,*(void**)(base+0x496650));
    return width>=0?width:original_width(s);
}
static int font_width_hook(const char *s,void *font) {
    int width=zh_width(s,font);
    return width>=0?width:original_font_width(s,font);
}
static int block_hook(const char *s,int length,int x,int y,int width,int height,int skip,unsigned char centered) {
    int lines=zh_draw_block(s,length,(float)x,(float)y,width,height,skip,centered);
    static BOOL logged;
    if(lines>=0 && !logged) {log_line("Unicode raw paragraph translated: length=%d xy=%d,%d area=%d,%d lines=%d",length,x,y,width,height,lines);logged=TRUE;}
    return lines>=0?lines:original_block(s,length,x,y,width,height,skip,centered);
}
static void float_block_hook(const char *s,int length,float x,float y,int width,int height,int skip,unsigned char centered) {
    if(zh_draw_block(s,length,x,y,width,height,skip,centered)<0) original_float_block(s,length,x,y,width,height,skip,centered);
}
static int block_lines_hook(const char *s,int length,int width,void *font) {
    int lines=zh_block_lines(s,length,width,font);
    return lines>=0?lines:original_block_lines(s,length,width,font);
}
__declspec(dllexport) BOOL WINAPI ExanimaZhInitialize(void) {
    if(InterlockedCompareExchange(&initialized,1,0)) return FALSE;
    wchar_t path[MAX_PATH]; DWORD n=GetModuleFileNameW(self,path,MAX_PATH);
    if(!n || n>=MAX_PATH) return FALSE;
    wchar_t *slash=wcsrchr(path,L'\\'); if(!slash || slash-path>MAX_PATH-40) return FALSE;
    wcscpy(slash+1,L"ExanimaZh"); CreateDirectoryW(path,NULL);
    wcscat(path,L"\\logs"); CreateDirectoryW(path,NULL);
    wcscat(path,L"\\latest.log");
    logfile=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
    log_line("ExanimaZh Unicode localization preview; external dictionary enabled.");
    if(!verify_exe()) {log_line("UNSUPPORTED VERSION: no hooks installed; English passthrough.");return FALSE;}
    base=(unsigned char*)GetModuleHandleW(NULL);
    if(!zh_load(self,base,log_line)) log_line("Unicode assets missing/invalid: diagnostic English passthrough.");
    Hook hooks[]={
        {base+0x34d20,draw_hook,{0x55,0x48,0x89,0xe5,0x48,0x8d,0xa4,0x24,0xf0,0xfe,0xff,0xff,0x48,0x89,0x9d,0x28,0xff,0xff,0xff},19,NULL},
        {base+0x35540,measure_hook,{0x53,0x57,0x56,0x41,0x54,0x41,0x55,0x41,0x56,0x41,0x57,0x48,0x8d,0x64,0x24,0xb0},16,NULL},
        {base+0x26f20,label_hook,{0x53,0x57,0x56,0x41,0x54,0x48,0x8d,0x64,0x24,0x98,0x66,0x0f,0x7f,0x74,0x24,0x20},16,NULL},
        {base+0x270b0,batch_hook,{0x53,0x57,0x56,0x41,0x54,0x48,0x8d,0x64,0x24,0x98,0x66,0x0f,0x7f,0x74,0x24,0x20},16,NULL},
        {base+0x26da0,width_hook,{0x31,0xc0,0x48,0x89,0xca,0x48,0x85,0xc9,0x74,0x04,0x48,0x8b,0x52,0xf8},14,NULL},
        {base+0x26de0,font_width_hook,{0x31,0xc0,0x49,0x89,0xc8,0x48,0x85,0xc9,0x74,0x04,0x4d,0x8b,0x40,0xf8},14,NULL},
        {base+0x27230,center_hook,{0x53,0x57,0x56,0x41,0x54,0x48,0x8d,0x64,0x24,0x88,0x66,0x0f,0x7f,0x74,0x24,0x20},16,NULL},
        {base+0x27920,clip_hook,{0x53,0x57,0x56,0x41,0x54,0x41,0x55,0x41,0x56,0x48,0x8d,0x64,0x24,0x98},14,NULL},
        {base+0x27d40,block_hook,{0x55,0x48,0x89,0xe5,0x48,0x8d,0xa4,0x24,0x10,0xff,0xff,0xff,0x48,0x89,0x9d,0x30,0xff,0xff,0xff},19,NULL},
        {base+0x280a0,float_block_hook,{0x55,0x48,0x89,0xe5,0x48,0x8d,0xa4,0x24,0x00,0xff,0xff,0xff,0x48,0x89,0x9d,0x20,0xff,0xff,0xff},19,NULL},
        {base+0x28410,block_lines_hook,{0x53,0x57,0x56,0x41,0x54,0x41,0x55,0x41,0x56,0x41,0x57,0x49,0x89,0xcf},14,NULL}
    };
    const size_t count=sizeof(hooks)/sizeof(hooks[0]);
    for(size_t i=0;i<count;i++) if(!prepare_hook(&hooks[i])) {log_line("Signature/trampoline validation failed at hook %zu; no hooks installed.",i);return FALSE;}
    original_draw=(DrawFn)hooks[0].trampoline; original_measure=(MeasureFn)hooks[1].trampoline;
    original_label=(LabelFn)hooks[2].trampoline;original_batch=(LabelFn)hooks[3].trampoline;
    original_width=(WidthFn)hooks[4].trampoline;original_font_width=(FontWidthFn)hooks[5].trampoline;
    original_center=(CenteredFn)hooks[6].trampoline;original_clip=(ClippedFn)hooks[7].trampoline;
    original_block=(BlockFn)hooks[8].trampoline;original_float_block=(FloatBlockFn)hooks[9].trampoline;
    original_block_lines=(BlockLinesFn)hooks[10].trampoline;
    if(!install_hooks(hooks,count)) {log_line("Could not safely install hooks; English passthrough.");return FALSE;}
    log_line("Verified %zu text/width hooks installed.",count);return TRUE;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)reserved;
    if(reason==DLL_PROCESS_ATTACH) {self=instance;DisableThreadLibraryCalls(instance);}
    return TRUE;
}
