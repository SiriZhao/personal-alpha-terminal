from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

SERVICE_PREFIX = "PersonalAlphaTerminal"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CredentialStoreError(RuntimeError):
    """A safe credential-store error that never contains a secret."""


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def credential_target(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"openai", "deepseek", "anthropic", "custom"}:
        raise ValueError("unsupported credential provider")
    return f"{SERVICE_PREFIX}/{normalized}/api-key"


def write_api_key(provider: str, api_key: str) -> None:
    secret = api_key.strip()
    if not secret:
        raise ValueError("API key cannot be empty")
    if sys.platform != "win32":
        raise CredentialStoreError("Windows Credential Manager is unavailable")
    blob = secret.encode("utf-8")
    if len(blob) > 5120:
        raise ValueError("API key exceeds Windows Credential Manager limit")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _Credential()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = credential_target(provider)
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = os.environ.get("USERNAME", "PersonalAlphaTerminal")
    function = ctypes.windll.advapi32.CredWriteW
    function.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(credential), 0):
        raise CredentialStoreError("Windows Credential Manager rejected the credential")


def read_api_key(provider: str) -> str | None:
    if sys.platform != "win32":
        return None
    pointer = ctypes.POINTER(_Credential)()
    function = ctypes.windll.advapi32.CredReadW
    function.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    function.restype = wintypes.BOOL
    if not function(credential_target(provider), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        return None
    try:
        credential = pointer.contents
        payload = ctypes.string_at(
            credential.CredentialBlob,
            credential.CredentialBlobSize,
        )
        return payload.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as error:
        raise CredentialStoreError("stored credential cannot be decoded") from error
    finally:
        ctypes.windll.advapi32.CredFree(pointer)


def delete_api_key(provider: str) -> bool:
    if sys.platform != "win32":
        return False
    function = ctypes.windll.advapi32.CredDeleteW
    function.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    function.restype = wintypes.BOOL
    return bool(function(credential_target(provider), CRED_TYPE_GENERIC, 0))


def load_credentials_into_environment() -> None:
    for provider, variable in (
        ("openai", "OPENAI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("custom", "CUSTOM_API_KEY"),
    ):
        if os.environ.get(variable):
            continue
        secret = read_api_key(provider)
        if secret:
            os.environ[variable] = secret
