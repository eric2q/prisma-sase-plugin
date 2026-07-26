"""Auth Manager -- OAuth2 client_credentials token cache with auto-renew.

Implements design doc sec.3 / sec.4.1 exactly (handoff note sec.10.2: do not
change the token endpoint or scope format):

* POST ``grant_type=client_credentials`` to the token endpoint with HTTP Basic
  auth (client_id as username, client_secret as password) and
  ``scope=tsg_id:<TSG_ID>``.
* Access tokens live 15 minutes. Cache in memory per TSG and renew ~2 minutes
  before expiry (a ~13-minute effective TTL).
* ``client_secret`` is read from the environment only and is NEVER written to
  logs, errors, or the response returned to the model.
"""
import base64
import logging
import threading
import time

import httpx

import config

log = logging.getLogger("prisma_sase.auth")


class AuthError(RuntimeError):
    """Raised when an access token cannot be obtained."""


class _CachedToken:
    __slots__ = ("token", "expires_at")

    def __init__(self, token, expires_at):
        self.token = token
        self.expires_at = expires_at


class AuthManager:
    """Singleton token cache keyed by TSG id (supports multi-tenant use)."""

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._tokens = {}            # tsg_id -> _CachedToken
        self._lock = threading.Lock()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_token(self, tsg_id=None, force=False):
        """Return a valid bearer token for the tenant, fetching/renewing as needed."""
        tsg = config.resolve_tsg(tsg_id)
        if not tsg:
            raise AuthError("No TSG id available: set PRISMA_TSG_ID or pass tsg_id.")

        if config.MOCK_MODE:
            return "MOCK.token.not-a-real-jwt"

        now = time.time()
        with self._lock:
            cached = self._tokens.get(tsg)
            if (not force) and cached and (cached.expires_at - now) > config.TOKEN_RENEW_MARGIN:
                return cached.token
            token, expires_in = self._fetch(tsg)
            self._tokens[tsg] = _CachedToken(token, now + expires_in)
            return token

    def invalidate(self, tsg_id=None):
        """Drop a cached token (used after a 401 to force a fresh fetch)."""
        tsg = config.resolve_tsg(tsg_id)
        with self._lock:
            self._tokens.pop(tsg, None)

    # -- internal ---------------------------------------------------------
    def _fetch(self, tsg):
        if not config.CLIENT_ID or not config.CLIENT_SECRET:
            msg = ("Missing PRISMA_CLIENT_ID / PRISMA_CLIENT_SECRET. Easiest "
                   "fix: fill in the plugin's enable dialog (Desktop: "
                   "Settings -> Plugins -> prisma-sase; the Claude Code CLI "
                   "prompts for the same four values on enable) -- the secret "
                   "goes to secure storage, and a full app restart applies "
                   "it. Without that dialog (cloud session, CI, standalone "
                   "install), use ~/.prisma-sase.env (chmod 600) or "
                   "PRISMA_SECRET_CMD. These are deliberately NOT tool "
                   "parameters: credentials must never travel through the "
                   "conversation.")
            # A host-side gap outranks the generic advice above: telling
            # someone to "fill in the enable dialog" is useless when the
            # dialog is exactly what never ran. userconfig_diagnosis()
            # subsumes placeholder_hint() (its "unexpanded" case).
            diag = config.userconfig_diagnosis()
            if diag:
                msg = ("Missing PRISMA_CLIENT_ID / PRISMA_CLIENT_SECRET. "
                       + diag["message"])
            raise AuthError(msg)
        # Basic header built by hand so the secret never lands in a log/URL.
        raw = "{0}:{1}".format(config.CLIENT_ID, config.CLIENT_SECRET).encode("utf-8")
        basic = base64.b64encode(raw).decode("ascii")
        headers = {
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {"grant_type": "client_credentials", "scope": "tsg_id:" + tsg}

        # Log the scope (tsg), never the credentials or the returned token.
        log.info("Requesting access token (scope=tsg_id:%s)", tsg)
        try:
            resp = httpx.post(config.AUTH_URL, headers=headers, data=data,
                              timeout=config.HTTP_TIMEOUT)
        except httpx.HTTPError as e:
            raise AuthError("Token request could not reach the auth server: %s" % e) from e

        if resp.status_code in (400, 401):
            # Deliberately do NOT echo the response body (may leak hints/secrets).
            raise AuthError(
                "Token request rejected (HTTP %d). Verify PRISMA_CLIENT_ID / "
                "PRISMA_CLIENT_SECRET and that the service account belongs to TSG "
                "%s with a read-only role." % (resp.status_code, tsg)
            )
        if resp.status_code >= 400:
            raise AuthError("Token endpoint returned HTTP %d." % resp.status_code)

        try:
            payload = resp.json()
        except ValueError:
            raise AuthError("Token endpoint returned a non-JSON response.")

        token = payload.get("access_token")
        if not token:
            raise AuthError("Token endpoint response contained no access_token.")
        try:
            expires_in = int(payload.get("expires_in", config.TOKEN_LIFETIME_FALLBACK))
        except (TypeError, ValueError):
            expires_in = config.TOKEN_LIFETIME_FALLBACK
        log.info("Access token acquired (scope=tsg_id:%s, expires_in=%ss)", tsg, expires_in)
        return token, expires_in
