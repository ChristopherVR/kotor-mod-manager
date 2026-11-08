"""
Sign in to Nexus Mods with OAuth 2.0 (authorization code + PKCE).

Follows the Nexus Mods guide "Using OAuth 2.0 and PKCE in your application"
(https://modding.wiki/en/api/oauth2-guide) and the provider's discovery
document (https://users.nexusmods.com/.well-known/openid-configuration):

1. `begin()` makes a PKCE code verifier and S256 challenge plus a random
   `state`, and returns the authorize URL. The app opens it in the browser.
2. The player approves the app on nexusmods.com. Nexus redirects the browser to
   the registered callback URI. For a desktop app the guide recommends a
   listener on 127.0.0.1; ours is a route on the app's own local backend
   (`redirect_uri()`), so no extra port is opened.
3. `complete()` checks the state, swaps the code (with the verifier) for tokens
   at the token endpoint, and verifies the access token's RS256 signature
   against the Nexus public key before trusting anything in it.
4. API calls (v1 and v2) send `Authorization: Bearer <access token>`.
   `access_token()` checks the expiry first and uses the refresh token when it
   has run out. A 4xx on refresh means the player revoked access, so the
   sign-in is forgotten and the player is asked to sign in again.

This is a public client: there is no client secret, PKCE protects the code. The
client ID is issued by Nexus Mods support and goes in `CLIENT_ID` below. Until it
is set, `available()` is False and the Sign in button stays disabled. Developers
can try a client ID without rebuilding through the KMI_NEXUS_CLIENT_ID
environment variable.

Tokens live in the OS keyring, never in config.json. Windows caps a single
credential at 2560 bytes and a JWT can be longer, so they are stored in chunks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

try:
    import keyring
except ImportError:  # keyring is optional for library use
    keyring = None

# The client ID Nexus Mods issued to this app. A public client has no secret, so
# this is safe to ship in source. Empty until Nexus registers the app.
CLIENT_ID = ""

# From https://users.nexusmods.com/.well-known/openid-configuration
_BASE = "https://users.nexusmods.com/oauth"
AUTHORIZE_URL = f"{_BASE}/authorize"
TOKEN_URL = f"{_BASE}/token"
REVOKE_URL = f"{_BASE}/revoke"
JWKS_URL = f"{_BASE}/discovery/keys"
# The guide uses an empty scope ("Use an empty string for no scopes"). Downloads
# through the v1 API need nothing more.
SCOPE = ""

CALLBACK_PATH = "/nexus/oauth/callback"
DEFAULT_PORT = 8756

# The public key printed in the Nexus guide for verifying access tokens. Keys
# from the JWKS endpoint are tried too, in case Nexus rotates or uses several.
NEXUS_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAs/57oX8HW8xC+W/etH7J
PgoSTiGPKZa6Gq3/K/7GgrpJcZhPdr9MTGocb2uLzQBJW+u1XpSgyeKH4JCxxeHF
3zcUtb7SUg3KnxlR5QUmOnqBvbUuL4opUpfgWUGltASduYqZBJD2WTK8Hvwh9X1v
ACeqp1zgorZm3f0J2H15TDbzIp9ihCFuthJUFumdzvrt/WvimW2fiyqndTNQwe5h
XM8hj8cemdWQXCd99qnj7UQkpu+yNisVMHQCsAqXITe6Ehp6IY9eCd4DJKjDvyLc
3vbY8UL+bcVK5tYAKemZ56uw3q1YdcyqGlItyLi4j4EISdBQaCCqT7YZUhMYzhUd
1QIDAQAB
-----END PUBLIC KEY-----"""

# Refresh this many seconds before the access token runs out, so a request never
# goes out with a token that expires on the way.
_REFRESH_MARGIN = 60
# How long a started sign-in waits for the player to approve it.
_FLOW_TIMEOUT = 600
# Clock difference allowed when checking a token's expiry.
_CLOCK_SKEW = 120

SERVICE_NAME = "kotor_mod_installer_nexus"
_CHUNK_COUNT_ENTRY = "__oauth_chunks__"
_CHUNK_ENTRY = "__oauth_{}__"
# Characters per keyring entry. Windows stores the secret as UTF-16 within 2560
# bytes, so stay well under 1280 characters.
_CHUNK_SIZE = 1000

_UA = "kotor-mod-installer"


class NexusOAuthError(Exception):
    """Signing in, refreshing or using the Nexus sign-in failed."""


class _TokenRejected(NexusOAuthError):
    """The token endpoint answered 4xx: the grant is expired, revoked or wrong."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def client_id() -> str:
    return CLIENT_ID or os.environ.get("KMI_NEXUS_CLIENT_ID", "").strip()


def available() -> bool:
    """Whether "Sign in with Nexus Mods" can be offered (a client ID is set)."""
    return bool(client_id())


_port = DEFAULT_PORT


def set_port(port: int) -> None:
    """Tell the module which port the local backend listens on."""
    global _port
    _port = int(port)


def redirect_uri() -> str:
    """The callback URI. Must match the one registered with Nexus exactly."""
    return f"http://127.0.0.1:{_port}{CALLBACK_PATH}"


# ---------------------------------------------------------------------------
# PKCE (RFC 7636)
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_verifier() -> str:
    """A cryptographically random 64-character verifier (43 to 128 allowed)."""
    return _b64url(secrets.token_bytes(48))


def challenge_for(verifier: str) -> str:
    """The S256 challenge: base64url(sha256(verifier)) without padding."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# ---------------------------------------------------------------------------
# JWT signature check (RS256), in plain Python
# ---------------------------------------------------------------------------
#
# RS256 is RSASSA-PKCS1-v1_5 with SHA-256 (RFC 7518 3.3, RFC 8017 8.2.2). The
# check is small enough to do directly, which avoids adding a crypto package to
# the frozen backend.

_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _der_read(buf: bytes, pos: int) -> tuple[int, int, int]:
    """Read one DER header at pos. Returns (tag, content start, content end)."""
    tag = buf[pos]
    length = buf[pos + 1]
    pos += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, pos, pos + length


def rsa_key_from_pem(pem: str) -> tuple[int, int]:
    """(n, e) from a PEM SubjectPublicKeyInfo RSA key."""
    body = "".join(line.strip() for line in pem.strip().splitlines()
                   if line.strip() and not line.startswith("-----"))
    der = base64.b64decode(body)
    _, p, _ = _der_read(der, 0)            # SubjectPublicKeyInfo SEQUENCE
    _, _, alg_end = _der_read(der, p)      # AlgorithmIdentifier
    tag, bs, _ = _der_read(der, alg_end)   # BIT STRING
    if tag != 0x03:
        raise ValueError("not an RSA public key")
    bs += 1                                # unused-bits byte
    _, p, _ = _der_read(der, bs)           # RSAPublicKey SEQUENCE
    _, ns, ne = _der_read(der, p)
    _, es, ee = _der_read(der, ne)
    return int.from_bytes(der[ns:ne], "big"), int.from_bytes(der[es:ee], "big")


def rsa_key_from_jwk(jwk: dict) -> tuple[int, int]:
    return (int.from_bytes(_b64url_decode(jwk["n"]), "big"),
            int.from_bytes(_b64url_decode(jwk["e"]), "big"))


def rs256_valid(signing_input: bytes, signature: bytes, key: tuple[int, int]) -> bool:
    n, e = key
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = _SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


_jwks_cache: dict = {"keys": [], "fetched": 0.0}


def _fetch_jwks() -> list[tuple[int, int]]:
    """RSA keys from the JWKS endpoint, cached for an hour."""
    if time.time() - _jwks_cache["fetched"] < 3600:
        return _jwks_cache["keys"]
    keys = []
    try:
        req = urllib.request.Request(JWKS_URL, headers={"User-Agent": _UA,
                                                        "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        for jwk in data.get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("n") and jwk.get("e"):
                keys.append(rsa_key_from_jwk(jwk))
    except Exception:
        pass  # Fall back to the documented key alone.
    _jwks_cache.update(keys=keys, fetched=time.time())
    return keys


def _verification_keys() -> list[tuple[int, int]]:
    return [rsa_key_from_pem(NEXUS_PUBLIC_KEY_PEM)] + _fetch_jwks()


def verify_jwt(token: str, keys: Optional[list] = None) -> dict:
    """
    Check an access token's RS256 signature and expiry and return its claims.
    Raises NexusOAuthError if it is malformed, not signed by Nexus, or expired.
    """
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url_decode(head_b64))
        claims = json.loads(_b64url_decode(body_b64))
        signature = _b64url_decode(sig_b64)
    except Exception as e:
        raise NexusOAuthError("Nexus Mods sent a sign-in token the app cannot read.") from e
    if header.get("alg") != "RS256":
        raise NexusOAuthError("Nexus Mods sent a sign-in token with an unexpected signature.")
    signing_input = f"{head_b64}.{body_b64}".encode("ascii")
    keys = _verification_keys() if keys is None else keys
    if not any(rs256_valid(signing_input, signature, k) for k in keys):
        raise NexusOAuthError("The sign-in token is not signed by Nexus Mods.")
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp + _CLOCK_SKEW < time.time():
        raise NexusOAuthError("The sign-in token from Nexus Mods has already expired.")
    return claims


# ---------------------------------------------------------------------------
# Sign-in flow
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_flow: dict = {"status": "idle"}   # idle | waiting | done | error | cancelled
_pending: dict = {}                # state, verifier, redirect_uri, client_id, started


def begin() -> str:
    """Start a sign-in and return the Nexus authorize URL to open in the browser."""
    cid = client_id()
    if not cid:
        raise NexusOAuthError("Nexus sign-in is not set up in this version of the app.")
    verifier = make_verifier()
    state = _b64url(secrets.token_bytes(32))
    redirect = redirect_uri()
    with _lock:
        _pending.clear()
        _pending.update(state=state, verifier=verifier, redirect_uri=redirect,
                        client_id=cid, started=time.time())
        _flow.clear()
        _flow["status"] = "waiting"
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": cid,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": redirect,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge_for(verifier),
    })


def cancel() -> None:
    with _lock:
        _pending.clear()
        if _flow.get("status") == "waiting":
            _flow.clear()
            _flow["status"] = "cancelled"


def flow_status() -> dict:
    """Where the current sign-in is, for the UI to poll."""
    with _lock:
        if (_flow.get("status") == "waiting" and _pending
                and time.time() - _pending["started"] > _FLOW_TIMEOUT):
            _pending.clear()
            _flow.clear()
            _flow.update(status="error", error="timed_out")
        return dict(_flow)


def _fail(error: str) -> None:
    with _lock:
        _pending.clear()
        _flow.clear()
        _flow.update(status="error", error=error)


def complete(code: str, state: str, error: str = "") -> dict:
    """
    Finish a sign-in from the callback's query parameters and return the account
    summary. Raises NexusOAuthError (and records it for flow_status) when the
    callback is not the one we are waiting for, the player declined, the token
    swap fails, or the token does not verify.
    """
    with _lock:
        pending = dict(_pending)
    expected = pending.get("state", "")
    if not expected or not state or not hmac.compare_digest(expected, state):
        # Not our sign-in (an old tab, or a forged link). A real pending sign-in
        # is left alone.
        raise NexusOAuthError("This sign-in link is out of date. Start again from the app.")
    if error:
        _fail("denied" if error == "access_denied" else error)
        raise NexusOAuthError("Sign-in was cancelled on Nexus Mods.")
    if not code:
        _fail("no_code")
        raise NexusOAuthError("Nexus Mods did not send a sign-in code.")
    try:
        tokens = _token_request({
            "grant_type": "authorization_code",
            "redirect_uri": pending["redirect_uri"],
            "scope": SCOPE,
            "client_id": pending["client_id"],
            "code": code,
            "code_verifier": pending["verifier"],
        })
        account = _store_tokens(tokens)
    except NexusOAuthError as e:
        _fail(str(e))
        raise
    with _lock:
        _pending.clear()
        _flow.clear()
        _flow.update(status="done", name=account.get("name", ""))
    return account


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------

def _post_form(url: str, fields: dict, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _token_request(fields: dict) -> dict:
    try:
        data = _post_form(TOKEN_URL, fields)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        msg = f"Nexus Mods refused the sign-in ({detail or f'HTTP {e.code}'})."
        if 400 <= e.code < 500:
            raise _TokenRejected(msg) from e
        raise NexusOAuthError(msg) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise NexusOAuthError(f"Could not reach Nexus Mods to sign in ({e}).") from e
    if not data.get("access_token"):
        raise NexusOAuthError("Nexus Mods sent no access token.")
    return data


def _account_from(tokens: dict, previous: Optional[dict] = None) -> dict:
    """What to keep from a token response, after verifying the access token."""
    claims = verify_jwt(tokens["access_token"])
    user = claims.get("user") if isinstance(claims.get("user"), dict) else {}
    roles = user.get("membership_roles") or []
    try:
        # The guide: expiry = time the token was received + expires_in.
        expires_at = time.time() + int(tokens["expires_in"])
    except (KeyError, TypeError, ValueError):
        expires_at = float(claims.get("exp") or time.time() + 3600)
    prev = previous or {}
    return {
        "access_token": tokens["access_token"],
        # A refresh may not hand out a new refresh token; keep the old one.
        "refresh_token": tokens.get("refresh_token") or prev.get("refresh_token", ""),
        "expires_at": expires_at,
        "user_id": user.get("id") or claims.get("sub") or prev.get("user_id", ""),
        "name": user.get("username") or prev.get("name", ""),
        "is_premium": "premium" in roles,
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_cache: Optional[dict] = None
_loaded = False


def _save(data: Optional[dict]) -> None:
    global _cache, _loaded
    _cache, _loaded = data, True
    if keyring is None:
        return
    try:
        old = int(keyring.get_password(SERVICE_NAME, _CHUNK_COUNT_ENTRY) or 0)
    except Exception:
        old = 0
    blob = json.dumps(data) if data else ""
    chunks = [blob[i:i + _CHUNK_SIZE] for i in range(0, len(blob), _CHUNK_SIZE)]
    try:
        for i, c in enumerate(chunks):
            keyring.set_password(SERVICE_NAME, _CHUNK_ENTRY.format(i), c)
        keyring.set_password(SERVICE_NAME, _CHUNK_COUNT_ENTRY, str(len(chunks)))
    except Exception:
        # No usable keyring: the sign-in lasts until the app closes.
        return
    for i in range(len(chunks), old):
        try:
            keyring.delete_password(SERVICE_NAME, _CHUNK_ENTRY.format(i))
        except Exception:
            pass
    if not chunks:
        try:
            keyring.delete_password(SERVICE_NAME, _CHUNK_COUNT_ENTRY)
        except Exception:
            pass


def _load() -> Optional[dict]:
    global _cache, _loaded
    if _loaded:
        return _cache
    _loaded = True
    if keyring is None:
        return None
    try:
        n = int(keyring.get_password(SERVICE_NAME, _CHUNK_COUNT_ENTRY) or 0)
        blob = "".join(keyring.get_password(SERVICE_NAME, _CHUNK_ENTRY.format(i)) or ""
                       for i in range(n))
        _cache = json.loads(blob) if blob else None
    except Exception:
        _cache = None
    return _cache


def _store_tokens(tokens: dict) -> dict:
    with _lock:
        account = _account_from(tokens, _load())
        _save(account)
        return account


# ---------------------------------------------------------------------------
# Using the sign-in
# ---------------------------------------------------------------------------

def signed_in() -> bool:
    with _lock:
        data = _load()
        return bool(data and data.get("access_token"))


def account() -> dict:
    """{signed_in, name, is_premium} for the UI. Never includes tokens."""
    with _lock:
        data = _load() or {}
    return {"signed_in": bool(data.get("access_token")),
            "name": data.get("name", ""),
            "is_premium": bool(data.get("is_premium"))}


_EXPIRED = "Your Nexus Mods sign-in has expired. Sign in again in Settings."


def refresh(force: bool = False) -> None:
    """Use the refresh token when the access token has run out (or if forced)."""
    with _lock:
        data = _load()
        if not data:
            raise NexusOAuthError("Not signed in to Nexus Mods.")
        if not force and data.get("expires_at", 0) - _REFRESH_MARGIN > time.time():
            return
        if not data.get("refresh_token"):
            _save(None)
            raise NexusOAuthError(_EXPIRED)
        try:
            tokens = _token_request({
                "client_id": client_id(),
                "grant_type": "refresh_token",
                "refresh_token": data["refresh_token"],
            })
        except _TokenRejected as e:
            # The guide: a 4xx here means access was revoked; treat as signed out.
            _save(None)
            raise NexusOAuthError(_EXPIRED) from e
        _save(_account_from(tokens, data))


def access_token() -> str:
    """A current access token, refreshed first if it has expired."""
    refresh()
    with _lock:
        return (_load() or {}).get("access_token", "")


def sign_out() -> None:
    """Forget the sign-in, and ask Nexus to revoke it when possible."""
    with _lock:
        data = _load()
        _save(None)
        _pending.clear()
        _flow.clear()
        _flow["status"] = "idle"
    cid = client_id()
    if data and cid:
        token = data.get("refresh_token") or data.get("access_token")
        try:
            _post_form(REVOKE_URL, {"token": token, "client_id": cid}, timeout=8)
        except Exception:
            pass  # Best effort: the local copy is gone either way.
