# -*- coding: utf-8 -*-
"""获取 GitHub token 并 DPAPI 加密保存到 %USERPROFILE%\\.workbuddy\\.gh_token.enc。

Windows 凭据管理器读取较慢（可能 60s+），故本脚本可独立后台运行：
    python tools/fetch_gh_token.py

产出：%USERPROFILE%\\.workbuddy\\.gh_token.enc（仅当前用户可解密，不入库）
"""
import base64
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _protect(plain: bytes) -> bytes:
    b, _ = _blob(plain)
    out = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(b), None, None, None, None, 0x01, ctypes.byref(out)):
        raise ctypes.WinError()
    cipher = ctypes.string_at(out.pbData, out.cbData)
    kernel32.LocalFree(out.pbData)
    return cipher


def _unprotect(cipher: bytes) -> bytes:
    b, _ = _blob(cipher)
    out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(b), None, None, None, None, 0x01, ctypes.byref(out)):
        raise ctypes.WinError()
    plain = ctypes.string_at(out.pbData, out.cbData)
    kernel32.LocalFree(out.pbData)
    return plain


ENC_PATH = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")), ".workbuddy", ".gh_token.enc"
)


def save_token(tok: str) -> None:
    os.makedirs(os.path.dirname(ENC_PATH), exist_ok=True)
    with open(ENC_PATH, "wb") as f:
        f.write(base64.b64encode(_protect(tok.encode("utf-8"))))
    print("[OK] token 已加密保存:", ENC_PATH)


def load_token() -> str:
    with open(ENC_PATH, "rb") as f:
        return _unprotect(base64.b64decode(f.read().strip())).decode("utf-8")


def fetch_from_credential_manager(attempts: int = 4) -> str:
    for i in range(1, attempts + 1):
        try:
            out = subprocess.run(
                ["git", "credential", "fill"],
                input="protocol=https\nhost=github.com\n\n",
                capture_output=True, text=True, timeout=150,
            ).stdout
        except Exception as e:  # noqa: BLE001
            print("  第 %d 次异常: %s" % (i, e))
            continue
        for line in out.splitlines():
            if line.startswith("password="):
                tok = line.split("=", 1)[1].strip()
                if tok:
                    print("  第 %d 次成功，长度 %d" % (i, len(tok)))
                    return tok
        print("  第 %d 次未返回 password，重试" % i)
        time.sleep(2)
    raise SystemExit("取不到 GitHub token")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        tok = load_token()
        print("token 前缀: %s 长度: %d" % (tok[:4], len(tok)))
        return
    tok = fetch_from_credential_manager()
    save_token(tok)
    print("完成")


if __name__ == "__main__":
    main()
