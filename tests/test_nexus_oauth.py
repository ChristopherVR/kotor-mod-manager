"""Tests for "Sign in with Nexus Mods" (OAuth 2.0 + PKCE).

Pins the flow to the Nexus guide (https://modding.wiki/en/api/oauth2-guide):
S256 PKCE, the authorize/token parameters, RS256 verification of the access
token, Bearer auth on the API, refresh on expiry, and a 4xx on refresh counting
as signed out. Tokens are signed with a throwaway RSA key made here.
"""

import base64
import hashlib
import io
import json
import secrets
import time
import urllib.error
import urllib.parse

import pytest

from scraper import nexus, nexus_oauth as oauth


# ---------------------------------------------------------------------------
# A throwaway RSA key and JWT signer
# ---------------------------------------------------------------------------

def _is_probable_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(20):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(c):
            return c


def _make_key(bits: int = 1024):
    e = 65537
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            n = p * q
            return (n, e), pow(e, -1, phi)


@pytest.fixture(scope="module")
def rsa_key():
    return _make_key()


@pytest.fixture(scope="module")
def other_key():
    return _make_key()


def _b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def sign_jwt(claims: dict, key) -> str:
    (n, _e), d = key
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = oauth._SHA256_DIGEST_INFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{head}.{body}.{_b64(sig)}"


def claims_for(name="TestAccount", roles=("member",), exp_in=21600):
    now = int(time.time())
    return {"application_id": 100, "exp": now + exp_in, "iat": now, "sub": "12345",
            "iss": "nexus-user-service",
            "user": {"id": 12345, "username": name, "membership_roles": list(roles),
                     "premium_expiry": 0}}


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, pw):
        self.store[(service, user)] = pw

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture(autouse=True)
def clean(monkeypatch, rsa_key):
    """Fresh state, a fake keyring, a test client ID, and our key as Nexus's."""
    ring = FakeKeyring()
    monkeypatch.setattr(oauth, "keyring", ring)
    monkeypatch.setattr(oauth, "CLIENT_ID", "kmi_test_client")
    monkeypatch.setattr(oauth, "_verification_keys", lambda: [rsa_key[0]])
    monkeypatch.setattr(oauth, "_cache", None)
    monkeypatch.setattr(oauth, "_loaded", False)
    oauth._pending.clear()
    oauth._flow.clear()
    oauth._flow["status"] = "idle"
    oauth.set_port(8756)
    return ring


def _query(url: str) -> dict:
    return {k: v[0] for k, v in urllib.parse.parse_qs(
        urllib.parse.urlparse(url).query, keep_blank_values=True).items()}


def _sign_in(monkeypatch, rsa_key, roles=("member",), refresh="rt-1", exp_in=21600):
    """Run a full sign-in against a fake token endpoint; returns its requests."""
    sent = []
    token = sign_jwt(claims_for(roles=roles, exp_in=exp_in), rsa_key)

    def fake_post(url, fields, timeout=20):
        sent.append((url, dict(fields)))
        return {"access_token": token, "refresh_token": refresh,
                "expires_in": exp_in, "token_type": "Bearer"}

    monkeypatch.setattr(oauth, "_post_form", fake_post)
    url = oauth.begin()
    oauth.complete("the-code", _query(url)["state"])
    return url, sent, token


# ---------------------------------------------------------------------------
# PKCE and the authorize URL
# ---------------------------------------------------------------------------

def test_s256_challenge_matches_the_rfc_7636_example():
    assert (oauth.challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
            == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")


def test_verifier_is_long_enough_and_url_safe():
    v = oauth.make_verifier()
    assert 43 <= len(v) <= 128
    assert set(v) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert oauth.make_verifier() != v


def test_authorize_url_has_the_parameters_the_guide_lists():
    url = oauth.begin()
    assert url.startswith("https://users.nexusmods.com/oauth/authorize?")
    q = _query(url)
    assert q["client_id"] == "kmi_test_client"
    assert q["response_type"] == "code"
    assert q["scope"] == ""
    assert q["redirect_uri"] == "http://127.0.0.1:8756/nexus/oauth/callback"
    assert q["code_challenge_method"] == "S256"
    assert q["code_challenge"] == oauth.challenge_for(oauth._pending["verifier"])
    assert len(q["state"]) >= 32
    assert oauth.flow_status()["status"] == "waiting"


def test_redirect_uri_follows_the_backend_port():
    oauth.set_port(9123)
    assert oauth.redirect_uri() == "http://127.0.0.1:9123/nexus/oauth/callback"


def test_not_available_without_a_client_id(monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    monkeypatch.delenv("KMI_NEXUS_CLIENT_ID", raising=False)
    assert not oauth.available()
    with pytest.raises(oauth.NexusOAuthError):
        oauth.begin()


def test_developer_client_id_from_the_environment(monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    monkeypatch.setenv("KMI_NEXUS_CLIENT_ID", " dev_client ")
    assert oauth.client_id() == "dev_client"


def test_built_in_client_id_wins(monkeypatch):
    monkeypatch.setenv("KMI_NEXUS_CLIENT_ID", "dev_client")
    assert oauth.client_id() == "kmi_test_client"


# ---------------------------------------------------------------------------
# Callback and token exchange
# ---------------------------------------------------------------------------

def test_token_exchange_sends_the_code_and_verifier(monkeypatch, rsa_key):
    url, sent, _ = _sign_in(monkeypatch, rsa_key)
    assert len(sent) == 1
    endpoint, fields = sent[0]
    assert endpoint == "https://users.nexusmods.com/oauth/token"
    assert fields["grant_type"] == "authorization_code"
    assert fields["code"] == "the-code"
    assert fields["client_id"] == "kmi_test_client"
    assert fields["redirect_uri"] == _query(url)["redirect_uri"]
    assert fields["scope"] == ""
    assert oauth.challenge_for(fields["code_verifier"]) == _query(url)["code_challenge"]
    assert "client_secret" not in fields  # public client
    assert oauth.flow_status() == {"status": "done", "name": "TestAccount"}


def test_signed_in_account_reads_name_and_premium(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key, roles=("member", "supporter", "premium"))
    assert oauth.account() == {"signed_in": True, "name": "TestAccount", "is_premium": True}


def test_free_account_is_not_premium(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key, roles=("member",))
    assert oauth.account()["is_premium"] is False


def test_wrong_state_is_refused_and_leaves_the_real_sign_in_waiting(monkeypatch):
    monkeypatch.setattr(oauth, "_post_form", lambda *a, **k: pytest.fail("must not swap"))
    oauth.begin()
    with pytest.raises(oauth.NexusOAuthError):
        oauth.complete("code", "forged-state")
    assert oauth.flow_status()["status"] == "waiting"
    assert not oauth.signed_in()


def test_callback_without_a_pending_sign_in_is_refused():
    with pytest.raises(oauth.NexusOAuthError):
        oauth.complete("code", "anything")


def test_declining_on_nexus_ends_the_sign_in(monkeypatch):
    url = oauth.begin()
    with pytest.raises(oauth.NexusOAuthError):
        oauth.complete("", _query(url)["state"], error="access_denied")
    assert oauth.flow_status() == {"status": "error", "error": "denied"}


def test_a_token_not_signed_by_nexus_is_rejected(monkeypatch, other_key):
    forged = sign_jwt(claims_for(roles=("premium",)), other_key)
    monkeypatch.setattr(oauth, "_post_form",
                        lambda *a, **k: {"access_token": forged, "expires_in": 21600})
    url = oauth.begin()
    with pytest.raises(oauth.NexusOAuthError, match="not signed by Nexus"):
        oauth.complete("code", _query(url)["state"])
    assert not oauth.signed_in()
    assert oauth.flow_status()["status"] == "error"


def test_a_tampered_token_is_rejected(rsa_key):
    token = sign_jwt(claims_for(roles=("member",)), rsa_key)
    head, body, sig = token.split(".")
    rich = _b64(json.dumps(claims_for(roles=("premium",))).encode())
    with pytest.raises(oauth.NexusOAuthError):
        oauth.verify_jwt(f"{head}.{rich}.{sig}", [rsa_key[0]])
    assert oauth.verify_jwt(token, [rsa_key[0]])["user"]["username"] == "TestAccount"


def test_documented_nexus_public_key_parses():
    n, e = oauth.rsa_key_from_pem(oauth.NEXUS_PUBLIC_KEY_PEM)
    assert n.bit_length() == 2048 and e == 65537


def test_token_endpoint_error_is_reported(monkeypatch):
    def refuse(url, fields, timeout=20):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"error":"invalid_grant"}'))
    monkeypatch.setattr(oauth, "_post_form", refuse)
    url = oauth.begin()
    with pytest.raises(oauth.NexusOAuthError, match="invalid_grant"):
        oauth.complete("code", _query(url)["state"])


# ---------------------------------------------------------------------------
# Storage, refresh, sign-out
# ---------------------------------------------------------------------------

def test_tokens_are_stored_in_small_keyring_chunks(monkeypatch, rsa_key, clean):
    _, _, token = _sign_in(monkeypatch, rsa_key)
    chunks = int(clean.store[(oauth.SERVICE_NAME, "__oauth_chunks__")])
    assert all(len(v) <= oauth._CHUNK_SIZE for v in clean.store.values())
    # A fresh process reads it back.
    monkeypatch.setattr(oauth, "_cache", None)
    monkeypatch.setattr(oauth, "_loaded", False)
    assert oauth.access_token() == token
    assert chunks >= 1


def test_expired_token_is_refreshed_before_use(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key)
    oauth._cache["expires_at"] = time.time() - 10
    new = sign_jwt(claims_for(name="Renamed"), rsa_key)
    sent = []

    def fake_post(url, fields, timeout=20):
        sent.append(fields)
        return {"access_token": new, "expires_in": 21600}  # no new refresh token
    monkeypatch.setattr(oauth, "_post_form", fake_post)

    assert oauth.access_token() == new
    assert sent == [{"client_id": "kmi_test_client", "grant_type": "refresh_token",
                     "refresh_token": "rt-1"}]
    assert oauth._cache["refresh_token"] == "rt-1"  # kept
    assert oauth.account()["name"] == "Renamed"


def test_valid_token_is_not_refreshed(monkeypatch, rsa_key):
    _, _, token = _sign_in(monkeypatch, rsa_key)
    monkeypatch.setattr(oauth, "_post_form", lambda *a, **k: pytest.fail("no refresh"))
    assert oauth.access_token() == token


def test_refresh_rejected_means_signed_out(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key)
    oauth._cache["expires_at"] = time.time() - 10

    def refuse(url, fields, timeout=20):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(oauth, "_post_form", refuse)
    with pytest.raises(oauth.NexusOAuthError, match="expired"):
        oauth.access_token()
    assert not oauth.signed_in()


def test_refresh_network_error_keeps_the_sign_in(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key)
    oauth._cache["expires_at"] = time.time() - 10

    def offline(url, fields, timeout=20):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(oauth, "_post_form", offline)
    with pytest.raises(oauth.NexusOAuthError):
        oauth.access_token()
    assert oauth.signed_in()


def test_sign_out_revokes_and_forgets(monkeypatch, rsa_key, clean):
    _sign_in(monkeypatch, rsa_key)
    sent = []
    monkeypatch.setattr(oauth, "_post_form",
                        lambda url, fields, timeout=20: sent.append((url, fields)) or {})
    oauth.sign_out()
    assert not oauth.signed_in()
    assert sent == [("https://users.nexusmods.com/oauth/revoke",
                     {"token": "rt-1", "client_id": "kmi_test_client"})]
    assert not any(k[1].startswith("__oauth_") for k in clean.store)


# ---------------------------------------------------------------------------
# Using the sign-in for the Nexus API
# ---------------------------------------------------------------------------

class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_api_requests_use_a_bearer_token(monkeypatch, rsa_key):
    _, _, token = _sign_in(monkeypatch, rsa_key)
    seen = []

    def fake_urlopen(req, timeout=10):
        seen.append({k.lower(): v for k, v in req.header_items()})
        return _Resp(b'{"name": "TestAccount", "is_premium": false}')
    monkeypatch.setattr(nexus.urllib.request, "urlopen", fake_urlopen)

    v = nexus.validate(nexus.OAUTH)
    assert v["ok"]
    h = seen[0]
    assert h["authorization"] == f"Bearer {token}"
    assert "apikey" not in h
    assert h["application-name"] == nexus.APP_NAME
    assert h["application-version"]


def test_a_401_refreshes_once_and_retries(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key)
    new = sign_jwt(claims_for(name="AfterRefresh"), rsa_key)
    monkeypatch.setattr(oauth, "_post_form",
                        lambda *a, **k: {"access_token": new, "expires_in": 21600})
    calls = []

    def fake_urlopen(req, timeout=10):
        calls.append(req.get_header("Authorization"))
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return _Resp(b'{"name": "TestAccount"}')
    monkeypatch.setattr(nexus.urllib.request, "urlopen", fake_urlopen)

    assert nexus.validate(nexus.OAUTH)["ok"]
    assert calls[1] == f"Bearer {new}" != calls[0]


def test_current_auth_is_the_sign_in(monkeypatch, rsa_key):
    assert nexus.current_auth() is None
    _sign_in(monkeypatch, rsa_key)
    assert nexus.current_auth() is nexus.OAUTH


def test_no_sign_in_without_a_client_id(monkeypatch, rsa_key):
    _sign_in(monkeypatch, rsa_key)
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    monkeypatch.delenv("KMI_NEXUS_CLIENT_ID", raising=False)
    assert nexus.current_auth() is None


def test_no_api_key_header_is_ever_sent():
    assert nexus._auth_headers("raw-token") == {"Authorization": "Bearer raw-token"}
    assert nexus._auth_headers(None) == {}


def test_typed_client_id_is_remembered_and_used(monkeypatch):
    saved = {}
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    monkeypatch.delenv("KMI_NEXUS_CLIENT_ID", raising=False)
    monkeypatch.setattr("config.load", lambda: dict(saved))
    monkeypatch.setattr("config.save", lambda c: saved.update(c))
    assert not oauth.available()
    oauth.set_client_id("  typed_client ")
    assert saved["nexus_oauth_client_id"] == "typed_client"
    assert oauth.available() and not oauth.built_in_client_id()
    assert _query(oauth.begin())["client_id"] == "typed_client"


def test_typed_client_id_never_replaces_a_built_in_one(monkeypatch):
    monkeypatch.setattr("config.save", lambda c: pytest.fail("must not save"))
    oauth.set_client_id("other")
    assert oauth.client_id() == "kmi_test_client" and oauth.built_in_client_id()


def test_start_route_saves_the_typed_client_id(monkeypatch):
    from backend import server
    from backend.models import NexusOAuthStartRequest
    saved = {}
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    monkeypatch.delenv("KMI_NEXUS_CLIENT_ID", raising=False)
    monkeypatch.setattr("config.load", lambda: dict(saved))
    monkeypatch.setattr("config.save", lambda c: saved.update(c))
    out = server.nexus_oauth_start(NexusOAuthStartRequest(client_id="from_box"))
    assert out["ok"] and _query(out["url"])["client_id"] == "from_box"
    state = server.nexus_oauth_state()
    assert state["built_in_client"] is False and state["client_id"] == "from_box"
