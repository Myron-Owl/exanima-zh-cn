#define WIN32_LEAN_AND_MEAN
#define WINMMAPI
#include <windows.h>
#include <mmsystem.h>
#include <wchar.h>

static HMODULE self, real;
static INIT_ONCE system_once = INIT_ONCE_STATIC_INIT;
static INIT_ONCE runtime_once = INIT_ONCE_STATIC_INIT;
static BOOL CALLBACK load_system(PINIT_ONCE once, PVOID parameter, PVOID *context) {
    (void)once; (void)parameter; (void)context;
    wchar_t path[MAX_PATH];
    UINT n = GetSystemDirectoryW(path, MAX_PATH);
    if (n && n < MAX_PATH-12) {
        wcscat(path, L"\\winmm.dll");
        real = LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    }
    return TRUE;
}
static FARPROC resolve(const char *name) {
    InitOnceExecuteOnce(&system_once, load_system, NULL, NULL);
    return real ? GetProcAddress(real, name) : NULL;
}
static BOOL CALLBACK load_runtime(PINIT_ONCE once, PVOID parameter, PVOID *context) {
    (void)once; (void)parameter; (void)context;
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(self, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return TRUE;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (!slash || slash-path > MAX_PATH-18) return TRUE;
    wcscpy(slash+1, L"ExanimaZh.dll");
    HMODULE runtime = LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (runtime) {
        BOOL (WINAPI *init)(void) = (void*)GetProcAddress(runtime, "ExanimaZhInitialize");
        if (init) init();
    }
    return TRUE;
}
// Initialization occurs on an exported timer call, never inside DllMain.
#define FORWARD(ret, name, args, call, fallback) \
__declspec(dllexport) ret WINAPI name args { \
    ret (WINAPI *fn) args = (void*)resolve(#name); \
    return fn ? fn call : fallback; \
}
__declspec(dllexport) DWORD WINAPI timeGetTime(void) {
    DWORD (WINAPI *fn)(void) = (void*)resolve("timeGetTime");
    InitOnceExecuteOnce(&runtime_once, load_runtime, NULL, NULL);
    return fn ? fn() : GetTickCount();
}
FORWARD(MMRESULT,timeBeginPeriod,(UINT u),(u),TIMERR_NOCANDO)
FORWARD(MMRESULT,timeEndPeriod,(UINT u),(u),TIMERR_NOCANDO)
FORWARD(UINT,waveInGetNumDevs,(void),(),0)
FORWARD(UINT,waveOutGetNumDevs,(void),(),0)
FORWARD(MMRESULT,waveInGetDevCapsW,(UINT_PTR u, LPWAVEINCAPSW c, UINT s),(u,c,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveOutGetDevCapsW,(UINT_PTR u, LPWAVEOUTCAPSW c, UINT s),(u,c,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveInOpen,(LPHWAVEIN h,UINT u,LPCWAVEFORMATEX f,DWORD_PTR c,DWORD_PTR i,DWORD g),(h,u,f,c,i,g),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveOutOpen,(LPHWAVEOUT h,UINT u,LPCWAVEFORMATEX f,DWORD_PTR c,DWORD_PTR i,DWORD g),(h,u,f,c,i,g),MMSYSERR_ERROR)
#define HEADER(name,type) FORWARD(MMRESULT,name,(type h,LPWAVEHDR p,UINT s),(h,p,s),MMSYSERR_ERROR)
HEADER(waveInAddBuffer,HWAVEIN)
HEADER(waveInPrepareHeader,HWAVEIN)
HEADER(waveInUnprepareHeader,HWAVEIN)
HEADER(waveOutPrepareHeader,HWAVEOUT)
HEADER(waveOutUnprepareHeader,HWAVEOUT)
HEADER(waveOutWrite,HWAVEOUT)
#define HANDLE_ONLY(name,type) FORWARD(MMRESULT,name,(type h),(h),MMSYSERR_ERROR)
HANDLE_ONLY(waveInClose,HWAVEIN)
HANDLE_ONLY(waveInReset,HWAVEIN)
HANDLE_ONLY(waveInStart,HWAVEIN)
HANDLE_ONLY(waveInStop,HWAVEIN)
HANDLE_ONLY(waveOutClose,HWAVEOUT)
HANDLE_ONLY(waveOutPause,HWAVEOUT)
HANDLE_ONLY(waveOutReset,HWAVEOUT)
HANDLE_ONLY(waveOutRestart,HWAVEOUT)
FORWARD(MMRESULT,timeGetDevCaps,(LPTIMECAPS p,UINT s),(p,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveOutGetPosition,(HWAVEOUT h,LPMMTIME p,UINT s),(h,p,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveInGetErrorTextW,(MMRESULT e,LPWSTR p,UINT s),(e,p,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveOutGetErrorTextW,(MMRESULT e,LPWSTR p,UINT s),(e,p,s),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveInMessage,(HWAVEIN h,UINT m,DWORD_PTR a,DWORD_PTR b),(h,m,a,b),MMSYSERR_ERROR)
FORWARD(MMRESULT,waveOutMessage,(HWAVEOUT h,UINT m,DWORD_PTR a,DWORD_PTR b),(h,m,a,b),MMSYSERR_ERROR)
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) { self = instance; DisableThreadLibraryCalls(instance); }
    return TRUE;
}
