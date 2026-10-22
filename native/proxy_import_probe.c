/* Static named imports reproduce loader binding without calling device setters. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>

__declspec(dllexport) unsigned WINAPI ProxyProbeCount(void) {
    unsigned count = 0;
#define RETAIN(name) do { __typeof__(&name) volatile pointer = &name; if (pointer) ++count; } while (0)
    RETAIN(mixerClose);
    RETAIN(mixerGetControlDetailsA); RETAIN(mixerGetControlDetailsW);
    RETAIN(mixerGetDevCapsA); RETAIN(mixerGetDevCapsW);
    RETAIN(mixerGetID);
    RETAIN(mixerGetLineControlsA); RETAIN(mixerGetLineControlsW);
    RETAIN(mixerGetLineInfoA); RETAIN(mixerGetLineInfoW);
    RETAIN(mixerGetNumDevs); RETAIN(mixerMessage);
    RETAIN(mixerOpen); RETAIN(mixerSetControlDetails);
    RETAIN(timeGetTime); RETAIN(timeGetDevCaps);
    RETAIN(timeBeginPeriod); RETAIN(timeEndPeriod);
    RETAIN(waveInGetNumDevs); RETAIN(waveOutGetNumDevs);
#undef RETAIN
    return count;
}
