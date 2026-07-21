"""Minimal stdlib client for the local Ollama daemon.

Only localhost may ever be contacted; the base URL comes from MEM_OLLAMA_URL
(the test seam for up/down/hung daemon states). Every call carries a strict
timeout so a hung daemon can never stall a caller.
"""

import json
import os
import urllib.error
import urllib.request

VERSION_TIMEOUT = 2.0
EMBED_TIMEOUT = 10.0
TAGS_TIMEOUT = 2.0


class OllamaError(Exception):
    """One-line, user-facing Ollama failure."""


def _reason(exc: OSError) -> str:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, TimeoutError):
        return "timed out"
    return str(reason)


def check_version(base_url: str, timeout: float = VERSION_TIMEOUT) -> str:
    """Return the daemon version, or raise OllamaError if unreachable."""
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
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        for entry in data.get("models") or []:
            if entry.get("name") == model or entry.get("model") == model:
                return str(entry.get("digest") or "unknown")
    except (OSError, ValueError):
        pass
    return "unknown"
