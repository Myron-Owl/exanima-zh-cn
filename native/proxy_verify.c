/* Runs only in an isolated test directory. Never opens a multimedia device. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static unsigned checks, failures;
#define CHECK(condition, label) do { \
    ++checks; if (!(condition)) { ++failures; fprintf(stderr, "FAIL: %s\n", label); } \
} while (0)
#define PAIR(name) \
    __typeof__(&name) p_##name = (void *)GetProcAddress(proxy, #name); \
    __typeof__(&name) s_##name = (void *)GetProcAddress(system, #name); \
    if (!p_##name || !s_##name) { fprintf(stderr, "Missing callable: %s\n", #name); return 1; }
#define REJECT(name, ...) do { \
    MMRESULT system_result = s_##name(__VA_ARGS__); \
    MMRESULT proxy_result = p_##name(__VA_ARGS__); \
    CHECK(system_result == proxy_result && system_result != MMSYSERR_NOERROR, #name " invalid handle"); \
} while (0)

static int sibling(const wchar_t *name, wchar_t path[MAX_PATH]) {
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (!slash || (size_t)(slash - path) + 1 + wcslen(name) >= MAX_PATH) return 0;
    wcscpy(slash + 1, name);
    return 1;
}

int main(int argc, char **argv) {
    int expect_missing = 0, startup = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--expect-missing")) expect_missing = 1;
        else if (!strcmp(argv[i], "--startup")) startup = 1;
        else return 2;
    }
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX | SEM_NOGPFAULTERRORBOX);
    if (GetModuleHandleW(L"winmm.dll")) {
        fputs("Host unexpectedly preloaded winmm.dll\n", stderr);
        return 1;
    }
    wchar_t path[MAX_PATH], actual[MAX_PATH];
    if (!sibling(L"proxy_import_probe.dll", path)) return 1;
    SetLastError(0);
    HMODULE probe = LoadLibraryExW(path, NULL,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    DWORD loader_error = probe ? 0 : GetLastError();
    if (expect_missing) {
        int passed = !probe && loader_error == ERROR_PROC_NOT_FOUND;
        printf("{\"passed\":%s,\"expected_missing_import\":true,\"loader_error\":%lu}\n",
            passed ? "true" : "false", (unsigned long)loader_error);
        return passed ? 0 : 1;
    }
    if (!probe) {
        printf("{\"passed\":false,\"loader_error\":%lu}\n", (unsigned long)loader_error);
        return 1;
    }
    unsigned (WINAPI *count_imports)(void) = (void *)GetProcAddress(probe, "ProxyProbeCount");
    if (!count_imports) return 1;
    unsigned import_count = count_imports();
    CHECK(import_count == 20, "static import probe retains all 20 addresses");

    HMODULE proxy = GetModuleHandleW(L"winmm.dll");
    if (!proxy || !sibling(L"winmm.dll", path)) return 1;
    DWORD actual_length = GetModuleFileNameW(proxy, actual, MAX_PATH);
    int local_proxy = actual_length && actual_length < MAX_PATH && !_wcsicmp(path, actual);
    CHECK(local_proxy, "Windows loader bound the proxy beside the host");
    if (!local_proxy) return 1;
    if (startup) {
        // No WinMM function is called in this branch. The host is named
        // Exanima.exe but its unknown hash must be rejected by the runtime.
        if (!sibling(L"ExanimaZh\\logs\\latest.log", path)) return 1;
        int refused = 0, loaded = 0;
        for (int attempt = 0; attempt < 500; ++attempt) {
            loaded = GetModuleHandleW(L"ExanimaZh.dll") != NULL;
            HANDLE log = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                    NULL, OPEN_EXISTING, 0, NULL);
            if (log != INVALID_HANDLE_VALUE) {
                char buffer[4096]; DWORD size = 0;
                if (ReadFile(log, buffer, sizeof(buffer)-1, &size, NULL)) {
                    buffer[size] = 0;
                    refused = strstr(buffer, "UNSUPPORTED VERSION: no hooks installed; English passthrough.") != NULL;
                }
                CloseHandle(log);
            }
            if (loaded && refused) break;
            Sleep(10);
        }
        int passed = loaded && refused;
        printf("{\"passed\":%s,\"runtime_loaded\":%s,\"unknown_hash_refused\":%s,\"winmm_functions_called\":0}\n",
               passed ? "true" : "false", loaded ? "true" : "false", refused ? "true" : "false");
        return passed ? 0 : 1;
    }
    UINT n = GetSystemDirectoryW(path, MAX_PATH);
    if (!n || n >= MAX_PATH - 12) return 1;
    wcscat(path, L"\\winmm.dll");
    HMODULE system = LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!system || system == proxy) return 1;
    actual_length = GetModuleFileNameW(system, actual, MAX_PATH);
    CHECK(actual_length && actual_length < MAX_PATH && !_wcsicmp(path, actual), "absolute system DLL path");
    CHECK(!GetModuleHandleW(L"ExanimaZh.dll"), "loader and address references do not initialize runtime");

    PAIR(mixerGetNumDevs)
    PAIR(mixerGetDevCapsA)
    PAIR(mixerGetDevCapsW)
    PAIR(mixerGetControlDetailsA)
    PAIR(mixerGetControlDetailsW)
    PAIR(mixerGetLineControlsA)
    PAIR(mixerGetLineControlsW)
    PAIR(mixerGetLineInfoA)
    PAIR(mixerGetLineInfoW)
    PAIR(mixerGetID)
    PAIR(mixerSetControlDetails)
    PAIR(waveInGetNumDevs)
    PAIR(waveOutGetNumDevs)
    PAIR(timeGetDevCaps)
    PAIR(timeGetTime)
    PAIR(timeBeginPeriod)
    PAIR(timeEndPeriod)

    UINT mixer_count = s_mixerGetNumDevs();
    CHECK(mixer_count == p_mixerGetNumDevs(), "mixer device count");
    MIXERCAPSA sa = {0}, pa = {0};
    MIXERCAPSW sw = {0}, pw = {0};
    MMRESULT sr = s_mixerGetDevCapsA(0, &sa, sizeof(sa));
    MMRESULT pr = p_mixerGetDevCapsA(0, &pa, sizeof(pa));
    CHECK(sr == pr && (sr != MMSYSERR_NOERROR || !memcmp(&sa, &pa, sizeof(sa))), "mixer ANSI capabilities");
    sr = s_mixerGetDevCapsW(0, &sw, sizeof(sw));
    pr = p_mixerGetDevCapsW(0, &pw, sizeof(pw));
    CHECK(sr == pr && (sr != MMSYSERR_NOERROR || !memcmp(&sw, &pw, sizeof(sw))), "mixer wide capabilities");

    /* HMIXER flag makes this an invalid HANDLE, never a device id or mapper. */
    HMIXEROBJ invalid = (HMIXEROBJ)(UINT_PTR)~(UINT_PTR)0;
    MIXERLINEA line_a = {.cbStruct = sizeof(line_a)};
    MIXERLINEW line_w = {.cbStruct = sizeof(line_w)};
    REJECT(mixerGetLineInfoA, invalid, &line_a, MIXER_OBJECTF_HMIXER | MIXER_GETLINEINFOF_DESTINATION);
    REJECT(mixerGetLineInfoW, invalid, &line_w, MIXER_OBJECTF_HMIXER | MIXER_GETLINEINFOF_DESTINATION);
    MIXERCONTROLA control_a = {.cbStruct = sizeof(control_a)};
    MIXERCONTROLW control_w = {.cbStruct = sizeof(control_w)};
    MIXERLINECONTROLSA controls_a = {.cbStruct = sizeof(controls_a), .cControls = 1,
        .cbmxctrl = sizeof(control_a), .pamxctrl = &control_a};
    MIXERLINECONTROLSW controls_w = {.cbStruct = sizeof(controls_w), .cControls = 1,
        .cbmxctrl = sizeof(control_w), .pamxctrl = &control_w};
    REJECT(mixerGetLineControlsA, invalid, &controls_a, MIXER_OBJECTF_HMIXER | MIXER_GETLINECONTROLSF_ALL);
    REJECT(mixerGetLineControlsW, invalid, &controls_w, MIXER_OBJECTF_HMIXER | MIXER_GETLINECONTROLSF_ALL);
    MIXERCONTROLDETAILS_UNSIGNED value = {0};
    MIXERCONTROLDETAILS details = {.cbStruct = sizeof(details), .cChannels = 1,
        .cbDetails = sizeof(value), .paDetails = &value};
    REJECT(mixerGetControlDetailsA, invalid, &details, MIXER_OBJECTF_HMIXER | MIXER_GETCONTROLDETAILSF_VALUE);
    REJECT(mixerGetControlDetailsW, invalid, &details, MIXER_OBJECTF_HMIXER | MIXER_GETCONTROLDETAILSF_VALUE);
    REJECT(mixerSetControlDetails, invalid, &details, MIXER_OBJECTF_HMIXER | MIXER_SETCONTROLDETAILSF_VALUE);
    UINT device_id = 0;
    REJECT(mixerGetID, invalid, &device_id, MIXER_OBJECTF_HMIXER);
    CHECK(s_waveInGetNumDevs() == p_waveInGetNumDevs(), "wave input device count");
    CHECK(s_waveOutGetNumDevs() == p_waveOutGetNumDevs(), "wave output device count");

    TIMECAPS st = {0}, pt = {0};
    sr = s_timeGetDevCaps(&st, sizeof(st));
    pr = p_timeGetDevCaps(&pt, sizeof(pt));
    CHECK(sr == pr && (sr != TIMERR_NOERROR || !memcmp(&st, &pt, sizeof(st))), "timer capabilities");
    CHECK(!GetModuleHandleW(L"ExanimaZh.dll"), "queries in a non-game host do not initialize runtime");

    unsigned char *base = (unsigned char *)GetModuleHandleW(NULL), *text = NULL;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    IMAGE_SECTION_HEADER *sections = IMAGE_FIRST_SECTION(nt);
    size_t text_size = 0;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i)
        if (!memcmp(sections[i].Name, ".text\0", 6)) {
            text = base + sections[i].VirtualAddress;
            text_size = sections[i].Misc.VirtualSize;
            break;
        }
    unsigned char *before = text_size ? malloc(text_size) : NULL;
    if (!before) return 1;
    memcpy(before, text, text_size);
    DWORD start = s_timeGetTime(), tick = p_timeGetTime(), end = s_timeGetTime();
    CHECK((DWORD)(tick - start) <= (DWORD)(end - start), "timer passthrough including DWORD wrap");
    int text_unchanged = !memcmp(before, text, text_size);
    CHECK(text_unchanged, "unsupported host executable text remains unchanged");
    free(before);
    int runtime_loaded = GetModuleHandleW(L"ExanimaZh.dll") != NULL;
    CHECK(!runtime_loaded, "non-game host does not load runtime, even through timeGetTime");

    UINT period = sr == TIMERR_NOERROR && st.wPeriodMin ? st.wPeriodMin : 1;
    MMRESULT sb = s_timeBeginPeriod(period), pb = p_timeBeginPeriod(period);
    /* Always balance successful requests before evaluating assertions. */
    MMRESULT pe = pb == TIMERR_NOERROR ? p_timeEndPeriod(period) : pb;
    MMRESULT se = sb == TIMERR_NOERROR ? s_timeEndPeriod(period) : sb;
    CHECK(sb == pb && se == pe && (sb != TIMERR_NOERROR || se == TIMERR_NOERROR), "balanced timer period passthrough");
    printf("{\"passed\":%s,\"loader_error\":0,\"local_proxy_verified\":true,"
        "\"probe_import_count\":%u,\"checks\":%u,\"failures\":%u,\"mixer_devices\":%u,"
        "\"runtime_loaded\":%s,\"host_text_unchanged\":%s}\n",
        failures ? "false" : "true", import_count, checks, failures, mixer_count,
        runtime_loaded ? "true" : "false", text_unchanged ? "true" : "false");
    return failures ? 1 : 0;
}
