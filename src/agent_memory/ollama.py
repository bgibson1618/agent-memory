"""Minimal stdlib client for the local Ollama daemon.

Only localhost may ever be contacted; the base URL comes from MEM_OLLAMA_URL
(the test seam for up/down/hung daemon states). Every call carries a strict
timeout so a hung daemon can never stall a caller.
"""

import json
import urllib.error
import urllib.request

VERSION_TIMEOUT = 2.0
EMBED_TIMEOUT = 10.0


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


def probe_embed_dims(base_url: str, model: str, timeout: float = EMBED_TIMEOUT) -> int:
    """Embed a probe string and return the vector dimensionality."""
    req = urllib.request.Request(
        base_url + "/api/embed",
        data=json.dumps({"model": model, "input": ["dimension probe"]}).encode("utf-8"),
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
    if not embeddings or not isinstance(embeddings[0], list):
        raise OllamaError(f"no embedding returned for model '{model}'")
    return len(embeddings[0])
