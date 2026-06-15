"""Shared credential store for Nous OAuth — reads from Hermes auth.json.

This module reads Nous API credentials from a shared Hermes Agent auth.json
file (mounted into the container via Docker volume). It provides proactive
token refresh: before each API call, the caller gets a valid JWT. If the
JWT is near expiry (<=120s), this module refreshes it via OAuth and writes
the updated token back to auth.json — keeping both Hermes and Honcho fresh.

Auth Path:
  Invoke JWT: The OAuth access_token (with inference:invoke scope) IS the API key.
  Legacy agent_key minting is retired (HTTP 410).

Usage:
  provider = NousAuthProvider("/auth/hermes-auth.json")
  key = await provider.get_api_key()  # Always returns a valid key
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

PORTAL_URL = "https://portal.nousresearch.com"
TOKEN_ENDPOINT = f"{PORTAL_URL}/api/oauth/token"
CLIENT_ID = "hermes-cli"
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120  # Matches Hermes Agent's skew


# ── JWT helpers (stdlib only) ──────────────────────────────────────────────

def decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode the payload of a JWT (no signature verification).
    Returns dict or None if token is not a valid JWT."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:
        return None


def has_invoke_scope(token: str) -> bool:
    """Check if a JWT has the inference:invoke scope."""
    payload = decode_jwt_payload(token)
    if not payload:
        return False
    scope = payload.get("scope", "")
    if isinstance(scope, list):
        return "inference:invoke" in scope
    return "inference:invoke" in str(scope).split()


def jwt_ttl_seconds(token: str) -> int | None:
    """Return seconds until JWT expiry, or None if not a JWT."""
    payload = decode_jwt_payload(token)
    if not payload or "exp" not in payload:
        return None
    return int(payload["exp"] - time.time())


# ── NousAuthProvider ───────────────────────────────────────────────────────

class NousAuthProvider:
    """Reads Nous credentials from Hermes auth.json, refreshes if expired.

    Thread-safe via file locking. In-memory cache avoids unnecessary file
    reads when the cached key is still valid (TTL > 120s).
    """

    def __init__(
        self,
        auth_json_path: str | Path,
        fallback_api_key: str | None = None,
    ) -> None:
        self._path = Path(auth_json_path)
        self._fallback_api_key = fallback_api_key
        self._cached_key: str | None = None
        self._cached_exp: float = 0
        self._layout: str | None = None
        self._refresh_lock = asyncio.Lock()

    async def get_api_key(self, *, force_refresh: bool = False) -> str:
        """Return a valid Nous API key. Refreshes if expired.

        Fast path: cached key with >120s TTL (~0ms).
        Normal path: file read + JWT decode (~1ms).
        Refresh path: OAuth POST + file write (~500ms).

        Raises RuntimeError if no valid key can be obtained.
        """
        now = time.time()

        # Fast path: cached key still valid
        if (
            not force_refresh
            and self._cached_key
            and self._cached_exp > (now + ACCESS_TOKEN_REFRESH_SKEW_SECONDS)
        ):
            return self._cached_key

        # Read from auth.json
        state = self._read_credential()
        if state is None:
            return self._fallback_or_raise(
                f"Cannot read Nous credential from {self._path}. "
                "Ensure Hermes Agent auth.json is mounted."
            )

        agent_key = state.get("agent_key", "")
        if not agent_key:
            agent_key = state.get("access_token", "")
        if not agent_key:
            return self._fallback_or_raise(
                f"No agent_key or access_token found in Nous credential at {self._path}"
            )

        # Check JWT validity
        ttl = jwt_ttl_seconds(agent_key)
        if (
            not force_refresh
            and ttl is not None
            and ttl > ACCESS_TOKEN_REFRESH_SKEW_SECONDS
        ):
            self._cached_key = agent_key
            self._cached_exp = now + ttl
            return agent_key

        # Token expired or near-expiry — refresh
        async with self._refresh_lock:
            # Double-check: another coroutine may have refreshed while we waited
            if (
                not force_refresh
                and self._cached_key
                and self._cached_exp > (time.time() + ACCESS_TOKEN_REFRESH_SKEW_SECONDS)
            ):
                return self._cached_key

            # Re-read file (Hermes may have refreshed)
            state = self._read_credential()
            if state:
                agent_key = state.get("agent_key", "")
                if not agent_key:
                    agent_key = state.get("access_token", "")
                ttl = jwt_ttl_seconds(agent_key)
                if (
                    not force_refresh
                    and ttl is not None
                    and ttl > ACCESS_TOKEN_REFRESH_SKEW_SECONDS
                ):
                    self._cached_key = agent_key
                    self._cached_exp = time.time() + ttl
                    logger.info("Nous token refreshed by Hermes (TTL=%ds)", ttl)
                    return agent_key

            # Must refresh ourselves
            refresh_token = state.get("refresh_token") if state else None
            if not refresh_token:
                return self._fallback_or_raise(
                    f"No refresh_token in {self._path} — cannot auto-refresh. "
                    "Run Hermes Agent login or sync_nous_key.py login."
                )

            logger.info("Nous JWT expired (TTL=%s) — refreshing via OAuth...", ttl)
            try:
                new_state = await self._do_refresh(state, refresh_token)
            except RuntimeError as exc:
                return self._fallback_or_raise(str(exc))

            new_key = new_state.get("agent_key", "")
            new_ttl = jwt_ttl_seconds(new_key) or 0
            self._cached_key = new_key
            self._cached_exp = time.time() + new_ttl
            logger.info("Nous OAuth refresh complete — new TTL=%ds", new_ttl)
            return new_key

    def _fallback_or_raise(self, message: str) -> str:
        fallback = self._fallback_api_key or os.getenv("LLM_NOUS_API_KEY")
        if fallback:
            logger.warning("%s Falling back to LLM_NOUS_API_KEY.", message)
            self._cached_key = fallback
            ttl = jwt_ttl_seconds(fallback)
            self._cached_exp = time.time() + ttl if ttl is not None else 0
            return fallback
        raise RuntimeError(message)

    def _read_credential(self) -> dict[str, Any] | None:
        """Read auth.json and extract the Nous provider credential.

        Supported layouts:
          { "providers": { "nous": { "agent_key": "...", "refresh_token": "...", ... } } }
          { "access_token": "...", "refresh_token": "...", ... }
        """
        if not self._path.exists():
            logger.warning("auth.json not found at %s", self._path)
            return None
        try:
            data = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse %s: %s", self._path, exc)
            return None

        providers = data.get("providers")
        if isinstance(providers, dict) and isinstance(providers.get("nous"), dict):
            self._layout = "providers"
            nous = providers["nous"]
        else:
            self._layout = "flat"
            nous = data

        if not nous or not (nous.get("agent_key") or nous.get("access_token")):
            logger.warning("No nous agent_key/access_token found in %s", self._path)
            return None

        return nous

    async def _do_refresh(
        self, current_state: dict[str, Any] | None, refresh_token: str
    ) -> dict[str, Any]:
        """Refresh the OAuth access token and write back to auth.json."""
        # Run blocking HTTP in thread pool
        new_access, new_refresh = await asyncio.to_thread(
            _refresh_access_token, refresh_token
        )

        if not has_invoke_scope(new_access):
            logger.warning("Refreshed access_token lacks inference:invoke scope")

        # Build updated credential state
        ttl = jwt_ttl_seconds(new_access) or 900
        expires_at = datetime.fromtimestamp(
            time.time() + ttl, tz=timezone.utc
        ).isoformat()

        updated_state = dict(current_state or {})
        updated_state["access_token"] = new_access
        updated_state["refresh_token"] = new_refresh
        updated_state["agent_key"] = new_access  # Invoke JWT path
        updated_state["expires_at"] = expires_at

        # Write back to auth.json (locked, atomic)
        await asyncio.to_thread(self._write_credential, updated_state)
        return updated_state

    def _write_credential(self, updated_cred: dict[str, Any]) -> None:
        """Write updated credential back to auth.json with file locking.

        Preserves the existing Hermes auth.json structure:
          { "providers": { "nous": { ...updated fields... } } }
          or flat shared { "access_token": "...", "refresh_token": "...", ... }
        """
        lock_name = f"{self._path.stem}.lock" if self._layout == "flat" else "auth.lock"
        lock_path = self._path.parent / lock_name
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, "w") as lock_fd:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                try:
                    # Re-read to preserve other providers and fields
                    data = {}
                    if self._path.exists():
                        with suppress(Exception):
                            data = json.loads(self._path.read_text())

                    if self._layout == "flat" or "providers" not in data:
                        data.update(updated_cred)
                    else:
                        providers = data.setdefault("providers", {})
                        nous = providers.setdefault("nous", {})
                        nous.update(updated_cred)

                    # Atomic write
                    tmp = self._path.with_suffix(".tmp")
                    tmp.write_text(json.dumps(data, indent=2))
                    tmp.rename(self._path)
                    logger.info("Updated auth.json with refreshed Nous credential")
                finally:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError as exc:
            logger.error("Failed to write auth.json: %s", exc)
            raise RuntimeError(f"Cannot write to {self._path}: {exc}") from exc


# ── OAuth refresh (stdlib HTTP) ────────────────────────────────────────────

def _refresh_access_token(refresh_token: str) -> tuple[str, str]:
    """Exchange refresh_token for new access_token + refresh_token.
    Blocking call — run via asyncio.to_thread.
    """
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(TOKEN_ENDPOINT, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result["access_token"], result["refresh_token"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(
            f"Nous OAuth refresh failed (HTTP {exc.code}): {body}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Nous OAuth refresh failed: {exc}") from exc
