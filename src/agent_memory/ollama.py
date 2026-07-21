"""Minimal stdlib client for the local Ollama daemon.

Only localhost may ever be contacted - and that is enforced here, not just
documented (F12 zero egress): every entry point refuses a non-loopback base
URL before a single socket opens, so even a stray MEM_OLLAMA_URL cannot send
KB content off-box. The base URL comes from MEM_OLLAMA_URL (the test seam for
up/down/hung daemon states). Every call carries a strict timeout so a hung
daemon can never stall a caller.
"""

import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request

VERSION_TIMEOUT = 2.0
EMBED_TIMEOUT = 10.0
TAGS_TIMEOUT = 2.0


class OllamaError(Exception):
    """One-line, user-facing Ollama failure."""


def _require_loopback(base_url: str) -> None:
    """The KB is local-only for life: refuse any Ollama URL whose host is not
    loopback, before any DNS lookup or connect can happen."""
    host = urllib.parse.urlsplit(base_url).hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise OllamaError(
            f"refusing non-loopback Ollama URL {base_url}"
            " - the KB is local-only (zero egress); use a 127.0.0.1 endpoint"
        )


def _reason(exc: OSError) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, TimeoutError):
        return "timed out"
    return str(reason)


def check_version(base_url: str, timeout: float = VERSION_TIMEOUT) -> str:
    """Return the daemon version, or raise OllamaError if unreachable."""
    _require_loopback(base_url)
    try:
        with urllib.request.urlopen(base_url + "/api/version", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return str(data.get("version", "unknown"))
    except urllib.error.HTTPError as e:
        raise OllamaError(f"unexpected response from {base_url} (HTTP {e.code})") from e
    except (OSError, ValueError) as e:
        raise OllamaError(
            f"unreachable at {base_url} ({_reason(e) if isinstance(e, OSError) else e}) - is the daemon running?"
        ) from e


def embed(base_url: str, model: str, texts: list, timeout: float = EMBED_TIMEOUT) -> list:
    """Embed texts; returns one vector per text. num_ctx is set explicitly so
    behavior never depends on the packaging default."""
    _require_loopback(base_url)
    payload = {
        "model": model,
        "input": texts,
        "options": {"num_ctx": int(os.environ.get("MEM_EMBED_NUM_CTX", "8192"))},
    }
    req = urllib.request.Request(
        base_url + "/api/embed",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
        except ValueError:
            msg = ""
        raise OllamaError(
            f"embed model '{model}' unusable at {base_url}: {msg or f'HTTP {e.code}'}"
        ) from e
    except (OSError, ValueError) as e:
        raise OllamaError(f"embed request to {base_url} failed ({_reason(e) if isinstance(e, OSError) else e})") from e
    embeddings = data.get("embeddings") or []
    if len(embeddings) != len(texts) or not all(isinstance(v, list) and v for v in embeddings):
        raise OllamaError(f"no embedding returned for model '{model}'")
    return embeddings


def probe_embed_dims(base_url: str, model: str, timeout: float = EMBED_TIMEOUT) -> int:
    """Embed a probe string and return the vector dimensionality."""
    return len(embed(base_url, model, ["dimension probe"], timeout=timeout)[0])


def model_digest(base_url: str, model: str, timeout: float = TAGS_TIMEOUT) -> str:
    """The installed model's digest from /api/tags, or 'unknown' - digest is
    metadata worth stamping, never worth failing an embed over."""
    _require_loopback(base_url)
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        for entry in data.get("models") or []:
            if entry.get("name") == model or entry.get("model") == model:
                return str(entry.get("digest") or "unknown")
    except (OSError, ValueError):
        pass
    return "unknown"
