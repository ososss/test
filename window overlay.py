# -*- coding: utf-8 -*-
"""
window_overlay.py - 윈도우 색 필터 + 영역 가림 오버레이

요구 사항  Windows 10/11, 64비트 Python 3.8 이상 (외부 패키지 없음, 관리자 권한 불필요)
실행       python window_overlay.py    (콘솔 창에 상태와 좌표가 출력됩니다)
설정       같은 폴더의 window_overlay.json (스크립트와 같은 이름, 없으면 기본값으로 만들어짐)

기본 단축키 (설정 파일의 hotkeys에서 변경)
  Ctrl+Alt+F    필터 켜기/끄기
  Ctrl+Alt+M    가림 영역 전체 켜기/끄기
  Ctrl+Alt+1..  가림 영역 개별 켜기/끄기 (영역마다 "hotkey" 지정, 같은 키를 주면 묶어서 토글)
  Ctrl+Alt+P    좌표 따기: 마우스 위치를 창 기준으로 출력,
                같은 창에서 두 번 누르면 두 점을 모서리로 하는 영역 JSON을 만들어 클립보드에 복사
  Ctrl+Alt+R    설정 다시 읽기
  Ctrl+Alt+Q    종료

좌표 규칙 (left / top / right / bottom 각각, 기준은 대상 창의 왼쪽 위 모서리)
  0 이상 숫자   창 왼쪽(top·bottom은 위)에서의 거리(px)
  음수          창 오른쪽(아래)에서의 거리(px)     예: "bottom": -110
  "50%"         창 너비(높이)에 대한 비율          예: 오른쪽 끝 = "100%"
  dpi_scale이 true면 px 값은 배율 100% 기준이고, 모니터 배율에 맞춰 자동으로 곱해집니다.
"""

import ctypes
import json
import os
import struct
import sys

CONFIG_PATH = os.path.splitext(os.path.abspath(__file__))[0] + ".json"
CLASS_NAME = "WindowOverlay"

# MAGCOLOREFFECT 행렬: 행 = 입력 R, G, B, A, 상수 / 열 = 출력 R, G, B, A, (1)
PRESETS = {
    "smart_invert": [
        [0.574, -0.426, -0.426, 0.0, 0.0],
        [-1.430, -0.430, -1.430, 0.0, 0.0],
        [-0.144, -0.144, 0.856, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [1.0, 1.0, 1.0, 0.0, 1.0],
    ],
    "invert": [
        [-1.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, -1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [1.0, 1.0, 1.0, 0.0, 1.0],
    ],
    "dark_navy": [
        [0.457, -0.344, -0.341, 0.0, 0.0],
        [-1.138, -0.347, -1.144, 0.0, 0.0],
        [-0.115, -0.116, 0.685, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [0.902, 0.929, 0.953, 0.0, 1.0],
    ],
}

DEFAULT_CONFIG = {
    "refresh_ms": 16,
    "dpi_scale": True,
    "filter": {"start_on": True, "preset": "smart_invert", "matrix": None},
    "mask": {"start_on": True, "click_through": True, "alpha": 255, "color": "#1B1F27"},
    "hotkeys": {
        "filter": "ctrl+alt+f",
        "mask": "ctrl+alt+m",
        "pick": "ctrl+alt+p",
        "reload": "ctrl+alt+r",
        "quit": "ctrl+alt+q",
    },
    "profiles": [
        {
            "name": "기본",
            "enabled": True,
            "match": {"class": "LyncConversationWindowClass", "title_contains": ""},
            "base": "frame",
            "filter_area": {"left": 0, "top": 0, "right": "100%", "bottom": "100%"},
            "filter_holes": [],
            "masks": [
                {"name": "하단 버튼줄(예시)", "left": 0, "top": -44, "right": "100%", "bottom": "100%",
                 "hotkey": "ctrl+alt+1", "enabled": True},
                {"name": "사진 열(예시)", "left": 0, "top": 80, "right": 52, "bottom": -120,
                 "hotkey": "ctrl+alt+2", "enabled": True},
            ],
        }
    ],
}

# ---------------------------------------------------------------- Win32 상수
WS_POPUP, WS_CHILD, WS_VISIBLE = 0x80000000, 0x40000000, 0x10000000
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00000020, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x00080000, 0x08000000
WS_EX_TOPMOST, GWL_EXSTYLE = 0x00000008, -20
SW_HIDE = 0
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x0010, 0x0040, 0x0200
HWND_TOP = 0
GW_HWNDPREV, GA_ROOT = 3, 2
LWA_ALPHA = 0x2
WM_PAINT, WM_ERASEBKGND, WM_MOUSEACTIVATE = 0x000F, 0x0014, 0x0021
WM_TIMER, WM_HOTKEY = 0x0113, 0x0312
MA_NOACTIVATE = 3
RGN_OR, RGN_DIFF = 2, 4
MW_FILTERMODE_EXCLUDE = 0
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
MONITOR_DEFAULTTONEAREST, MDT_EFFECTIVE_DPI = 2, 0
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
IDC_ARROW = 32512
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
_VKEYS = {
    "space": 0x20, "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E,
    "pause": 0x13, "scrolllock": 0x91, "esc": 0x1B, "tab": 0x09,
    "`": 0xC0, "backquote": 0xC0, "-": 0xBD, "minus": 0xBD, "=": 0xBB, "equals": 0xBB,
}
_VKEYS.update({"f%d" % i: 0x6F + i for i in range(1, 25)})
_VKEYS.update({"numpad%d" % i: 0x60 + i for i in range(10)})


# ---------------------------------------------------------------- 순수 함수 (Windows API 없이 동작)
def resolve_edge(value, size, scale):
    """좌표 한 개를 창 왼쪽/위 기준 실제 px로 바꾼다."""
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            return int(round(size * float(text[:-1]) / 100.0))
        value = float(text)
    value = float(value)
    px = int(round(abs(value) * scale))
    return size - px if value < 0 else px


def resolve_rect(spec, width, height, scale):
    """{left, top, right, bottom} 설정을 창 기준 (l, t, r, b)로 바꾼다. 비어 있으면 None."""
    left = resolve_edge(spec.get("left", 0), width, scale)
    top = resolve_edge(spec.get("top", 0), height, scale)
    right = resolve_edge(spec.get("right", "100%"), width, scale)
    bottom = resolve_edge(spec.get("bottom", "100%"), height, scale)
    left, right = max(0, min(left, width)), max(0, min(right, width))
    top, bottom = max(0, min(top, height)), max(0, min(bottom, height))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def edge_value(rel, size, scale):
    """좌표 따기용: 가까운 쪽 모서리 기준 설정값을 만든다."""
    rel = max(0, min(rel, size))
    if rel <= size / 2:
        return int(round(rel / scale))
    dist = int(round((size - rel) / scale))
    return "100%" if dist == 0 else -dist


def parse_color(text, default=0x00271F1B):
    """'#RRGGBB' -> COLORREF(0x00BBGGRR)"""
    try:
        s = str(text).strip().lstrip("#")
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return r | (g << 8) | (b << 16)
    except (ValueError, IndexError):
        return default


def parse_hotkey(text):
    """'ctrl+alt+f' -> (modifiers, virtual key)"""
    parts = [p for p in str(text).replace(" ", "").lower().split("+") if p]
    mods, vk = 0, None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif p in _VKEYS:
            vk = _VKEYS[p]
        elif len(p) == 1 and p.isascii() and p.isalnum():
            vk = ord(p.upper())
        else:
            raise ValueError("알 수 없는 키 '%s'" % p)
    if vk is None:
        raise ValueError("수식키 말고 실제 키가 하나 있어야 합니다")
    return mods | MOD_NOREPEAT, vk


def format_hotkey(text):
    parts = [p for p in str(text).replace(" ", "").split("+") if p]
    return "+".join(p.upper() if len(p) == 1 else p.capitalize() for p in parts)


def match_profile(profile, cls, title):
    if not profile.get("enabled", True):
        return False
    m = profile.get("match") or {}
    want_cls = m.get("class") or ""
    want_title = (m.get("title_contains") or "").lower()
    if not want_cls and not want_title:
        return False
    if want_cls and cls != want_cls:
        return False
    if want_title and want_title not in (title or "").lower():
        return False
    return True


def matrix_for(filter_cfg):
    m = filter_cfg.get("matrix")
    if m:
        if len(m) != 5 or any(len(row) != 5 for row in m):
            raise ValueError("filter.matrix는 5x5 숫자 배열이어야 합니다")
        return [[float(v) for v in row] for row in m]
    name = filter_cfg.get("preset") or "smart_invert"
    if name not in PRESETS:
        raise ValueError("알 수 없는 preset '%s' (사용 가능: %s)" % (name, ", ".join(PRESETS)))
    return PRESETS[name]


def validate_regions(cfg):
    """좌표 형식 오류를 시작할 때 미리 잡는다."""
    for p in cfg.get("profiles") or []:
        pname = p.get("name", "?")
        specs = [("filter_area", p.get("filter_area") or {})]
        specs += [("filter_holes", s) for s in p.get("filter_holes") or []]
        specs += [(s.get("name", "masks"), s) for s in p.get("masks") or []]
        for label, spec in specs:
            try:
                resolve_rect(spec, 1000, 1000, 1.0)
            except (ValueError, TypeError) as e:
                raise ValueError("프로필 '%s'의 '%s' 좌표 오류: %s" % (pname, label, e))


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print("기본 설정 파일을 만들었습니다:", path)
        return cfg
    with open(path, encoding="utf-8-sig") as f:
        user = json.load(f)
    if not isinstance(user, dict):
        raise ValueError("설정 파일의 최상위는 { } 객체여야 합니다")
    for key, val in user.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    validate_regions(cfg)
    return cfg


# ---------------------------------------------------------------- Win32 바인딩
IS_WIN = os.name == "nt"

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    magdll = ctypes.WinDLL("Magnification", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None

    LRESULT = ctypes.c_ssize_t
    HANDLE, HWND = wintypes.HANDLE, wintypes.HWND
    BOOL, UINT, DWORD, INT = wintypes.BOOL, wintypes.UINT, wintypes.DWORD, ctypes.c_int
    PRECT, PPOINT = ctypes.POINTER(wintypes.RECT), ctypes.POINTER(wintypes.POINT)
    PMSG = ctypes.POINTER(wintypes.MSG)
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
    WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", UINT), ("style", UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", INT), ("cbWndExtra", INT), ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", HANDLE), ("hCursor", HANDLE), ("hbrBackground", HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                    ("hIconSm", HANDLE)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", HANDLE), ("fErase", BOOL), ("rcPaint", wintypes.RECT),
                    ("fRestore", BOOL), ("fIncUpdate", BOOL), ("rgbReserved", ctypes.c_byte * 32)]

    class MAGTRANSFORM(ctypes.Structure):
        _fields_ = [("v", (ctypes.c_float * 3) * 3)]

    class MAGCOLOREFFECT(ctypes.Structure):
        _fields_ = [("transform", (ctypes.c_float * 5) * 5)]

    def _fn(dll, name, restype, *argtypes):
        f = getattr(dll, name)
        f.restype = restype
        f.argtypes = list(argtypes)
        return f

    def _opt(dll, name, restype, *argtypes):
        if dll is None:
            return None
        try:
            return _fn(dll, name, restype, *argtypes)
        except AttributeError:
            return None

    RegisterClassExW = _fn(user32, "RegisterClassExW", wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
    CreateWindowExW = _fn(user32, "CreateWindowExW", HWND, DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                          DWORD, INT, INT, INT, INT, HWND, HANDLE, wintypes.HINSTANCE, ctypes.c_void_p)
    DestroyWindow = _fn(user32, "DestroyWindow", BOOL, HWND)
    DefWindowProcW = _fn(user32, "DefWindowProcW", LRESULT, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)
    ShowWindow = _fn(user32, "ShowWindow", BOOL, HWND, INT)
    SetWindowPos = _fn(user32, "SetWindowPos", BOOL, HWND, HWND, INT, INT, INT, INT, UINT)
    MoveWindow = _fn(user32, "MoveWindow", BOOL, HWND, INT, INT, INT, INT, BOOL)
    GetWindow = _fn(user32, "GetWindow", HWND, HWND, UINT)
    GetWindowLongPtrW = _fn(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, HWND, INT)
    IsWindow = _fn(user32, "IsWindow", BOOL, HWND)
    IsWindowVisible = _fn(user32, "IsWindowVisible", BOOL, HWND)
    IsIconic = _fn(user32, "IsIconic", BOOL, HWND)
    GetWindowRect = _fn(user32, "GetWindowRect", BOOL, HWND, PRECT)
    GetClientRect = _fn(user32, "GetClientRect", BOOL, HWND, PRECT)
    ClientToScreen = _fn(user32, "ClientToScreen", BOOL, HWND, PPOINT)
    EnumWindows = _fn(user32, "EnumWindows", BOOL, WNDENUMPROC, wintypes.LPARAM)
    GetClassNameW = _fn(user32, "GetClassNameW", INT, HWND, wintypes.LPWSTR, INT)
    GetWindowTextW = _fn(user32, "GetWindowTextW", INT, HWND, wintypes.LPWSTR, INT)
    SetLayeredWindowAttributes = _fn(user32, "SetLayeredWindowAttributes", BOOL, HWND,
                                     wintypes.COLORREF, wintypes.BYTE, DWORD)
    SetWindowRgn = _fn(user32, "SetWindowRgn", INT, HWND, HANDLE, BOOL)
    InvalidateRect = _fn(user32, "InvalidateRect", BOOL, HWND, ctypes.c_void_p, BOOL)
    BeginPaint = _fn(user32, "BeginPaint", HANDLE, HWND, ctypes.POINTER(PAINTSTRUCT))
    EndPaint = _fn(user32, "EndPaint", BOOL, HWND, ctypes.POINTER(PAINTSTRUCT))
    FillRect = _fn(user32, "FillRect", INT, HANDLE, PRECT, HANDLE)
    RegisterHotKey = _fn(user32, "RegisterHotKey", BOOL, HWND, INT, UINT, UINT)
    UnregisterHotKey = _fn(user32, "UnregisterHotKey", BOOL, HWND, INT)
    GetMessageW = _fn(user32, "GetMessageW", BOOL, PMSG, HWND, UINT, UINT)
    TranslateMessage = _fn(user32, "TranslateMessage", BOOL, PMSG)
    DispatchMessageW = _fn(user32, "DispatchMessageW", LRESULT, PMSG)
    PostQuitMessage = _fn(user32, "PostQuitMessage", None, INT)
    SetTimer = _fn(user32, "SetTimer", ctypes.c_size_t, HWND, ctypes.c_size_t, UINT, ctypes.c_void_p)
    KillTimer = _fn(user32, "KillTimer", BOOL, HWND, ctypes.c_size_t)
    GetCursorPos = _fn(user32, "GetCursorPos", BOOL, PPOINT)
    WindowFromPoint = _fn(user32, "WindowFromPoint", HWND, wintypes.POINT)
    GetAncestor = _fn(user32, "GetAncestor", HWND, HWND, UINT)
    MonitorFromWindow = _fn(user32, "MonitorFromWindow", HANDLE, HWND, DWORD)
    LoadCursorW = _fn(user32, "LoadCursorW", HANDLE, wintypes.HINSTANCE, ctypes.c_void_p)
    OpenClipboard = _fn(user32, "OpenClipboard", BOOL, HWND)
    EmptyClipboard = _fn(user32, "EmptyClipboard", BOOL)
    SetClipboardData = _fn(user32, "SetClipboardData", HANDLE, UINT, HANDLE)
    CloseClipboard = _fn(user32, "CloseClipboard", BOOL)
    SetProcessDpiAwarenessContext = _opt(user32, "SetProcessDpiAwarenessContext", BOOL, ctypes.c_void_p)
    SetProcessDPIAware = _opt(user32, "SetProcessDPIAware", BOOL)

    CreateSolidBrush = _fn(gdi32, "CreateSolidBrush", HANDLE, wintypes.COLORREF)
    DeleteObject = _fn(gdi32, "DeleteObject", BOOL, HANDLE)
    CreateRectRgn = _fn(gdi32, "CreateRectRgn", HANDLE, INT, INT, INT, INT)
    CombineRgn = _fn(gdi32, "CombineRgn", INT, HANDLE, HANDLE, HANDLE, INT)

    GetModuleHandleW = _fn(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
    GlobalAlloc = _fn(kernel32, "GlobalAlloc", HANDLE, UINT, ctypes.c_size_t)
    GlobalLock = _fn(kernel32, "GlobalLock", ctypes.c_void_p, HANDLE)
    GlobalUnlock = _fn(kernel32, "GlobalUnlock", BOOL, HANDLE)
    GlobalFree = _fn(kernel32, "GlobalFree", HANDLE, HANDLE)

    DwmGetWindowAttribute = _fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long,
                                HWND, DWORD, ctypes.c_void_p, DWORD)
    GetDpiForMonitor = _opt(shcore, "GetDpiForMonitor", ctypes.c_long, HANDLE, INT,
                            ctypes.POINTER(UINT), ctypes.POINTER(UINT))
    SetProcessDpiAwareness = _opt(shcore, "SetProcessDpiAwareness", ctypes.c_long, INT)

    MagInitialize = _fn(magdll, "MagInitialize", BOOL)
    MagUninitialize = _fn(magdll, "MagUninitialize", BOOL)
    MagSetWindowSource = _fn(magdll, "MagSetWindowSource", BOOL, HWND, wintypes.RECT)
    MagSetWindowTransform = _fn(magdll, "MagSetWindowTransform", BOOL, HWND, ctypes.POINTER(MAGTRANSFORM))
    MagSetColorEffect = _fn(magdll, "MagSetColorEffect", BOOL, HWND, ctypes.POINTER(MAGCOLOREFFECT))
    MagSetWindowFilterList = _fn(magdll, "MagSetWindowFilterList", BOOL, HWND, DWORD, INT,
                                 ctypes.POINTER(HWND))

    MASK_OWNERS = {}

    def _wndproc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_PAINT and hwnd in MASK_OWNERS:
                MASK_OWNERS[hwnd].paint(hwnd)
                return 0
            if msg == WM_ERASEBKGND and hwnd in MASK_OWNERS:
                return 1
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
        except Exception as e:
            print("  ! 그리기 오류:", e)
        return DefWindowProcW(hwnd, msg, wparam, lparam)

    WNDPROC_REF = WNDPROC(_wndproc)


# ---------------------------------------------------------------- Win32 도우미
def get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    GetWindowTextW(hwnd, buf, 512)
    return buf.value


def is_cloaked(hwnd):
    val = wintypes.DWORD(0)
    if DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val)) == 0:
        return val.value != 0
    return False


def get_base_rect(hwnd, base):
    """대상 창의 화면 좌표 (l, t, r, b). frame = 보이는 창 테두리, client = 클라이언트 영역"""
    rc = wintypes.RECT()
    if base == "client":
        if not GetClientRect(hwnd, ctypes.byref(rc)):
            return None
        pt = wintypes.POINT(0, 0)
        if not ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        return (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)
    if DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc)) == 0:
        return (rc.left, rc.top, rc.right, rc.bottom)
    if GetWindowRect(hwnd, ctypes.byref(rc)):
        return (rc.left, rc.top, rc.right, rc.bottom)
    return None


def get_scale(hwnd):
    if GetDpiForMonitor:
        mon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        dx, dy = wintypes.UINT(0), wintypes.UINT(0)
        if mon and GetDpiForMonitor(mon, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
            return dx.value / 96.0
    return 1.0


def region_union(rects):
    rgn = CreateRectRgn(0, 0, 0, 0)
    for left, top, right, bottom in rects:
        part = CreateRectRgn(left, top, right, bottom)
        CombineRgn(rgn, rgn, part, RGN_OR)
        DeleteObject(part)
    return rgn


def region_minus(width, height, holes):
    rgn = CreateRectRgn(0, 0, width, height)
    for left, top, right, bottom in holes:
        part = CreateRectRgn(left, top, right, bottom)
        CombineRgn(rgn, rgn, part, RGN_DIFF)
        DeleteObject(part)
    return rgn


def copy_to_clipboard(text, owner):
    """owner: 이 프로그램의 창 핸들 (NULL로 열면 SetClipboardData가 실패할 수 있음)"""
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not OpenClipboard(owner):
        return False
    try:
        EmptyClipboard()
        hmem = GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not hmem:
            return False
        ptr = GlobalLock(hmem)
        if not ptr:
            GlobalFree(hmem)
            return False
        ctypes.memmove(ptr, data, len(data))
        GlobalUnlock(hmem)
        if not SetClipboardData(CF_UNICODETEXT, hmem):
            GlobalFree(hmem)
            return False
        return True
    finally:
        CloseClipboard()


def set_dpi_awareness():
    if SetProcessDpiAwarenessContext and SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        return
    if SetProcessDpiAwareness and SetProcessDpiAwareness(2) == 0:
        return
    if SetProcessDPIAware:
        SetProcessDPIAware()


def register_window_class():
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = WNDPROC_REF
    wc.hInstance = GetModuleHandleW(None)
    wc.hCursor = LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    wc.lpszClassName = CLASS_NAME
    if not RegisterClassExW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())


# ---------------------------------------------------------------- 대상 창 하나에 붙는 오버레이
class Overlay:
    """필터 창(돋보기 컨트롤)과 가림 창을 대상 창 바로 위에 붙여서 따라다니게 한다."""

    def __init__(self, app, target, pi):
        self.app, self.target, self.pi = app, target, pi
        self.profile = app.cfg["profiles"][pi]
        hinst = GetModuleHandleW(None)

        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.host = CreateWindowExW(ex, CLASS_NAME, "window_overlay_filter", WS_POPUP,
                                    0, 0, 1, 1, None, None, hinst, None)
        if not self.host:
            raise ctypes.WinError(ctypes.get_last_error())
        SetLayeredWindowAttributes(self.host, 0, 255, LWA_ALPHA)
        self.mag = CreateWindowExW(0, "Magnifier", "window_overlay_mag", WS_CHILD | WS_VISIBLE,
                                   0, 0, 1, 1, self.host, None, hinst, None)
        if not self.mag:
            err = ctypes.get_last_error()
            DestroyWindow(self.host)
            raise ctypes.WinError(err)
        tf = MAGTRANSFORM()
        tf.v[0][0] = tf.v[1][1] = tf.v[2][2] = 1.0
        MagSetWindowTransform(self.mag, ctypes.byref(tf))
        eff = MAGCOLOREFFECT()
        for i in range(5):
            for j in range(5):
                eff.transform[i][j] = app.matrix[i][j]
        MagSetColorEffect(self.mag, ctypes.byref(eff))

        mcfg = app.cfg["mask"]
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if mcfg.get("click_through", True):
            ex |= WS_EX_TRANSPARENT
        self.mask = CreateWindowExW(ex, CLASS_NAME, "window_overlay_mask", WS_POPUP,
                                    0, 0, 1, 1, None, None, hinst, None)
        if not self.mask:
            err = ctypes.get_last_error()
            DestroyWindow(self.host)
            raise ctypes.WinError(err)
        alpha = max(0, min(255, int(mcfg.get("alpha", 255))))
        SetLayeredWindowAttributes(self.mask, 0, alpha, LWA_ALPHA)
        MASK_OWNERS[self.mask] = self

        self.rects = []
        self.host_geom = None
        self.mask_geom = None
        self.vis = {self.host: False, self.mask: False}

    def paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(hwnd, ctypes.byref(ps))
        try:
            for (left, top, right, bottom), color in self.rects:
                brush = CreateSolidBrush(color)
                FillRect(hdc, ctypes.byref(wintypes.RECT(left, top, right, bottom)), brush)
                DeleteObject(brush)
        finally:
            EndPaint(hwnd, ctypes.byref(ps))

    def _hide(self, hwnd):
        if self.vis.get(hwnd):
            ShowWindow(hwnd, SW_HIDE)
            self.vis[hwnd] = False

    def hide(self):
        self._hide(self.host)
        self._hide(self.mask)

    def destroy(self):
        MASK_OWNERS.pop(self.mask, None)
        DestroyWindow(self.mask)
        DestroyWindow(self.host)

    def _stacked(self, hwnds):
        """대상 창 바로 위에 hwnds가 순서대로 있는지 (숨겨 둔 우리 창은 건너뜀)"""
        below = self.target
        for hw in hwnds:
            above = GetWindow(below, GW_HWNDPREV)
            while above and above != hw and above in self.app.own and not IsWindowVisible(above):
                above = GetWindow(above, GW_HWNDPREV)
            if above != hw:
                return False
            below = hw
        return True

    def update(self):
        """매 틱 호출. 대상 창이 사라졌으면 False."""
        app, target = self.app, self.target
        if not IsWindow(target):
            return False
        if not IsWindowVisible(target) or IsIconic(target) or is_cloaked(target):
            self.hide()
            return True
        base = get_base_rect(target, self.profile.get("base") or "frame")
        if not base:
            self.hide()
            return True
        L, T, R, B = base
        W, H = R - L, B - T
        if W < 2 or H < 2:
            self.hide()
            return True
        s = get_scale(target) if app.dpi_scale else 1.0

        host_geom = None
        if app.filter_on:
            area = resolve_rect(self.profile.get("filter_area") or {}, W, H, s)
            if area:
                fl, ft, fr, fb = area
                holes = []
                for spec in self.profile.get("filter_holes") or []:
                    h = resolve_rect(spec, W, H, s)
                    if h:
                        holes.append((h[0] - fl, h[1] - ft, h[2] - fl, h[3] - ft))
                host_geom = (L + fl, T + ft, fr - fl, fb - ft, tuple(holes))

        mask_geom = None
        if app.mask_on:
            default = app.cfg["mask"].get("color") or "#1B1F27"
            rects = []
            for mi, spec in enumerate(self.profile.get("masks") or []):
                if not app.mask_enabled.get((self.pi, mi), True):
                    continue
                r = resolve_rect(spec, W, H, s)
                if r:
                    rects.append((r, parse_color(spec.get("color") or default)))
            if rects:
                mask_geom = (L, T, W, H, tuple(rects))

        if host_geom is None:
            self._hide(self.host)
        if mask_geom is None:
            self._hide(self.mask)

        changed = False
        if host_geom is not None and host_geom != self.host_geom:
            x, y, w, h, holes = host_geom
            MoveWindow(self.mag, 0, 0, w, h, False)
            if holes:
                SetWindowRgn(self.host, region_minus(w, h, holes), True)
            elif self.host_geom and self.host_geom[4]:
                SetWindowRgn(self.host, None, True)
            self.host_geom = host_geom
            changed = True
        if mask_geom is not None and mask_geom != self.mask_geom:
            self.rects = list(mask_geom[4])
            SetWindowRgn(self.mask, region_union([r for r, _ in self.rects]), True)
            self.mask_geom = mask_geom
            InvalidateRect(self.mask, None, True)
            changed = True

        stack = []
        if host_geom is not None:
            stack.append((self.host, host_geom[:4]))
        if mask_geom is not None:
            stack.append((self.mask, mask_geom[:4]))
        if stack and (changed or not all(self.vis[hw] for hw, _ in stack)
                      or not self._stacked([hw for hw, _ in stack])):
            # 대상 창 바로 위에 끼워 넣는다 (다른 창이 대상 창을 가리면 오버레이도 같이 가려짐)
            above = GetWindow(target, GW_HWNDPREV)
            while above and above in app.own:
                above = GetWindow(above, GW_HWNDPREV)
            if above and GetWindowLongPtrW(above, GWL_EXSTYLE) & WS_EX_TOPMOST:
                above = None  # 항상 위 창 아래에 끼우면 오버레이까지 항상 위가 되므로 일반 창 맨 위로
            after = above or HWND_TOP
            for hw, (x, y, w, h) in stack:
                SetWindowPos(hw, after, x, y, w, h, SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW)
                self.vis[hw] = True

        if host_geom is not None:
            x, y, w, h = host_geom[:4]
            MagSetWindowSource(self.mag, wintypes.RECT(x, y, x + w, y + h))
            InvalidateRect(self.mag, None, True)
        return True


# ---------------------------------------------------------------- 앱
class App:
    def __init__(self, path):
        self.path = path
        self.cfg = None
        self.overlays = {}
        self.own = set()
        self.hotkeys = {}
        self.hotkey_lines = []
        self.timer = 0
        self.pick_first = None
        self.tick_count = 0
        self.last_error = None
        self.clip_hwnd = CreateWindowExW(0, CLASS_NAME, "window_overlay_clipboard", WS_POPUP,
                                         0, 0, 0, 0, None, None, GetModuleHandleW(None), None)
        self.load()
        self.print_help()

    # ---- 설정
    def load(self):
        cfg = load_config(self.path)
        matrix = matrix_for(cfg["filter"])
        profiles = cfg.get("profiles") or []
        self.cfg = cfg
        self.matrix = matrix
        self.dpi_scale = bool(cfg.get("dpi_scale", True))
        self.refresh_ms = max(10, int(cfg.get("refresh_ms", 16)))
        self.discover_every = max(1, 250 // self.refresh_ms)
        self.filter_on = bool(cfg["filter"].get("start_on", True))
        self.mask_on = bool(cfg["mask"].get("start_on", True))
        self.mask_enabled = {(pi, mi): bool(m.get("enabled", True))
                             for pi, p in enumerate(profiles)
                             for mi, m in enumerate(p.get("masks") or [])}
        self.register_hotkeys()
        self.restart_timer()

    def restart_timer(self):
        if self.timer:
            KillTimer(None, self.timer)
        self.timer = SetTimer(None, 0, self.refresh_ms, None)

    def _register(self, hid, spec, action, label):
        if not spec:
            return
        try:
            mods, vk = parse_hotkey(spec)
        except ValueError as e:
            print("  ! 단축키 형식 오류 '%s': %s" % (spec, e))
            return
        if RegisterHotKey(None, hid, mods, vk):
            self.hotkeys[hid] = action
            self.hotkey_lines.append("  %-14s %s" % (format_hotkey(spec), label))
        else:
            print("  ! 단축키 등록 실패 '%s' (%s) - 이미 다른 곳에서 쓰는 조합일 수 있습니다" % (spec, label))

    def register_hotkeys(self):
        for hid in list(self.hotkeys):
            UnregisterHotKey(None, hid)
        self.hotkeys = {}
        self.hotkey_lines = []
        hk = self.cfg.get("hotkeys") or {}
        self._register(1, hk.get("filter"), self.toggle_filter, "필터 켜기/끄기")
        self._register(2, hk.get("mask"), self.toggle_mask, "가림 영역 전체 켜기/끄기")
        self._register(3, hk.get("pick"), self.pick, "좌표 따기 (같은 창에서 두 번 = 영역 JSON)")
        self._register(4, hk.get("reload"), self.reload, "설정 다시 읽기")
        self._register(5, hk.get("quit"), self.quit, "종료")
        groups = {}
        for pi, p in enumerate(self.cfg.get("profiles") or []):
            for mi, m in enumerate(p.get("masks") or []):
                spec = m.get("hotkey")
                if not spec:
                    continue
                try:
                    key = parse_hotkey(spec)
                except ValueError as e:
                    print("  ! 단축키 형식 오류 '%s': %s" % (spec, e))
                    continue
                g = groups.setdefault(key, {"spec": spec, "keys": [], "names": []})
                g["keys"].append((pi, mi))
                g["names"].append(m.get("name") or "영역 %d" % (mi + 1))
        hid = 100
        for g in groups.values():
            label = ", ".join(g["names"])
            self._register(hid, g["spec"], lambda k=g["keys"], l=label: self.toggle_masks(k, l),
                           "가림 [%s] 켜기/끄기" % label)
            hid += 1

    def print_help(self):
        print("=" * 64)
        print(" 윈도우 오버레이 실행 중   설정 파일:", self.path)
        for line in self.hotkey_lines:
            print(line)
        preset = "사용자 행렬" if self.cfg["filter"].get("matrix") else self.cfg["filter"].get("preset")
        print(" 현재: 필터 %s (%s) / 가림 %s" % ("켬" if self.filter_on else "끔", preset,
                                              "켬" if self.mask_on else "끔"))
        print("=" * 64)

    # ---- 동작
    def toggle_filter(self):
        self.filter_on = not self.filter_on
        print("[필터] %s" % ("켬" if self.filter_on else "끔"))
        self.tick()

    def toggle_mask(self):
        self.mask_on = not self.mask_on
        print("[가림 전체] %s" % ("켬" if self.mask_on else "끔"))
        self.tick()

    def toggle_masks(self, keys, label):
        new = not all(self.mask_enabled.get(k, True) for k in keys)
        for k in keys:
            self.mask_enabled[k] = new
        note = "" if self.mask_on else "  (가림 전체가 꺼져 있어 지금은 안 보입니다)"
        print("[가림] %s: %s%s" % (label, "켬" if new else "끔", note))
        self.tick()

    def match_index(self, cls, title):
        for pi, p in enumerate(self.cfg.get("profiles") or []):
            if match_profile(p, cls, title):
                return pi
        return None

    def pick(self):
        pt = wintypes.POINT()
        if not GetCursorPos(ctypes.byref(pt)):
            return
        hw = WindowFromPoint(pt)
        top = GetAncestor(hw, GA_ROOT) if hw else None
        for t, ov in self.overlays.items():
            if top in (ov.host, ov.mask):
                top = t
                break
        if not top:
            print("[좌표] 마우스 아래에서 창을 찾지 못했습니다.")
            return
        cls, title = get_class(top), get_title(top)
        pi = self.match_index(cls, title)
        profiles = self.cfg.get("profiles") or []
        base_name = (profiles[pi].get("base") or "frame") if pi is not None else "frame"
        base = get_base_rect(top, base_name)
        if not base:
            print("[좌표] 창 위치를 읽지 못했습니다.")
            return
        L, T, R, B = base
        W, H = R - L, B - T
        s = get_scale(top) if self.dpi_scale else 1.0
        x, y = pt.x - L, pt.y - T
        if pi is not None:
            where = "프로필 '%s'" % profiles[pi].get("name", pi)
        else:
            where = "일치하는 프로필 없음 - match.class에 위 class 값을 넣으세요"
        print('[좌표] class="%s"  title="%s"  (%s)' % (cls, title, where))
        print("  창 %dx%d, 배율 %.2f, 기준 %s" % (round(W / s), round(H / s), s, base_name))
        print("  왼쪽/위 기준 x=%d, y=%d   오른쪽/아래 기준 x=%d, y=%d"
              % (round(x / s), round(y / s), -round((W - x) / s), -round((H - y) / s)))
        if self.pick_first and self.pick_first[0] == top:
            _, x0, y0 = self.pick_first
            self.pick_first = None
            l, r = sorted((x0, x))
            t, b = sorted((y0, y))
            spec = {"name": "새 영역", "left": edge_value(l, W, s), "top": edge_value(t, H, s),
                    "right": edge_value(r, W, s), "bottom": edge_value(b, H, s)}
            text = json.dumps(spec, ensure_ascii=False)
            copied = bool(self.clip_hwnd) and copy_to_clipboard(text, self.clip_hwnd)
            print("  영역: %s%s" % (text, "   (클립보드에 복사됨)" if copied else ""))
        else:
            self.pick_first = (top, x, y)
            print("  -> 반대쪽 모서리로 옮겨 한 번 더 누르면 영역 JSON을 만듭니다.")

    def reload(self):
        print("[설정] 다시 읽는 중...")
        try:
            self.load()
        except Exception as e:
            print("  ! 설정 오류로 이전 설정을 유지합니다:", e)
            return
        for ov in list(self.overlays.values()):
            ov.destroy()
        self.overlays.clear()
        self.own = set()
        self.pick_first = None
        self.tick_count = 0
        self.print_help()
        self.tick()

    def quit(self):
        print("[종료] 오버레이를 닫습니다.")
        PostQuitMessage(0)

    # ---- 창 추적
    def rebuild_own(self):
        self.own = set()
        for ov in self.overlays.values():
            self.own.update((ov.host, ov.mask))
        hwnds = list(self.own)
        arr = (wintypes.HWND * len(hwnds))(*hwnds) if hwnds else None
        for ov in self.overlays.values():
            MagSetWindowFilterList(ov.mag, MW_FILTERMODE_EXCLUDE, len(hwnds), arr)

    def discover(self):
        profiles = self.cfg.get("profiles") or []
        need_title = any((p.get("match") or {}).get("title_contains") for p in profiles)
        found = {}

        def callback(hwnd, _lparam):
            try:
                if hwnd in self.own or not IsWindowVisible(hwnd):
                    return True
                cls = get_class(hwnd)
                title = get_title(hwnd) if need_title else ""
                for pi, p in enumerate(profiles):
                    if match_profile(p, cls, title):
                        found[hwnd] = pi
                        break
            except Exception:
                pass
            return True

        EnumWindows(WNDENUMPROC(callback), 0)
        changed = False
        for t in [t for t in self.overlays if t not in found]:
            self.overlays.pop(t).destroy()
            changed = True
        for t, pi in found.items():
            if t not in self.overlays:
                try:
                    self.overlays[t] = Overlay(self, t, pi)
                    changed = True
                except OSError as e:
                    print("  ! 오버레이 생성 실패:", e)
        if changed:
            self.rebuild_own()
            print("[대상] 감지된 창 %d개" % len(self.overlays))

    def tick(self):
        try:
            self.tick_count += 1
            if self.tick_count == 1 or self.tick_count % self.discover_every == 0:
                self.discover()
            dead = [t for t, ov in self.overlays.items() if not ov.update()]
            if dead:
                for t in dead:
                    self.overlays.pop(t).destroy()
                self.rebuild_own()
                print("[대상] 감지된 창 %d개" % len(self.overlays))
        except Exception as e:
            msg = "%s: %s" % (type(e).__name__, e)
            if msg != self.last_error:
                print("  ! 갱신 오류:", msg)
                self.last_error = msg

    def run(self):
        self.tick()
        msg = wintypes.MSG()
        while True:
            ret = GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY:
                action = self.hotkeys.get(msg.wParam)
                if action:
                    try:
                        action()
                    except Exception as e:
                        print("  ! 단축키 처리 오류:", e)
            elif msg.message == WM_TIMER and not msg.hWnd:
                self.tick()
            else:
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))

    def shutdown(self):
        if self.timer:
            KillTimer(None, self.timer)
            self.timer = 0
        for hid in list(self.hotkeys):
            UnregisterHotKey(None, hid)
        self.hotkeys = {}
        for ov in list(self.overlays.values()):
            ov.destroy()
        self.overlays.clear()
        self.own = set()
        if self.clip_hwnd:
            DestroyWindow(self.clip_hwnd)
            self.clip_hwnd = None


def main():
    if not IS_WIN:
        print("Windows 전용 프로그램입니다.")
        return 1
    if struct.calcsize("P") != 8:
        print("64비트 Python이 필요합니다. 돋보기 API는 32비트 프로세스에서 제대로 동작하지 않습니다.")
        return 1
    set_dpi_awareness()
    if not MagInitialize():
        print("돋보기 API 초기화(MagInitialize)에 실패했습니다.")
        return 1
    app = None
    try:
        register_window_class()
        app = App(CONFIG_PATH)
        app.run()
    except ValueError as e:
        print("설정 오류:", e)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if app is not None:
            app.shutdown()
        MagUninitialize()
    print("종료했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
