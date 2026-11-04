// LosslessCutter portable launcher: starts the bundled pythonw.exe with
// "-m losslesscutter", forwarding any arguments (e.g. a video file path).
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>
#include <stdlib.h>

static void append_quoted(wchar_t *dst, size_t cap, const wchar_t *arg) {
    size_t len = wcslen(dst);
    if (len + 1 < cap) { dst[len++] = L'"'; dst[len] = 0; }
    for (const wchar_t *p = arg; *p; p++) {
        if (*p == L'"' && len + 2 < cap) { dst[len++] = L'\\'; }
        if (len + 1 < cap) { dst[len++] = *p; dst[len] = 0; }
    }
    if (len + 1 < cap) { dst[len++] = L'"'; dst[len] = 0; }
    if (len + 1 < cap) { dst[len++] = L' '; dst[len] = 0; }
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR lpCmd, int nShow) {
    (void)hInst; (void)hPrev; (void)lpCmd; (void)nShow;
    wchar_t dir[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    wchar_t pythonw[MAX_PATH];
    _snwprintf(pythonw, MAX_PATH, L"%s\\pythonw.exe", dir);
    if (GetFileAttributesW(pythonw) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"pythonw.exe not found next to LosslessCutter.exe.\nKeep all files of the portable folder together.",
                    L"LosslessCutter", MB_OK | MB_ICONERROR);
        return 1;
    }

    static wchar_t cmd[32768];
    cmd[0] = 0;
    append_quoted(cmd, 32768, pythonw);
    wcscat_s(cmd, 32768, L"-m losslesscutter ");

    int argc = 0;
    PWSTR *argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        for (int i = 1; i < argc; i++) append_quoted(cmd, 32768, argv[i]);
        LocalFree(argv);
    }

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(pythonw, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        MessageBoxW(NULL, L"Failed to start the bundled Python runtime.",
                    L"LosslessCutter", MB_OK | MB_ICONERROR);
        return 1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
