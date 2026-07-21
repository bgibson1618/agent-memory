"""OKF concept schema - clean-room from the ARCHITECTURE/FEATURES field contract.

One concept = YAML frontmatter (id/slug, title, description, type, topics[],
sensitivity, created/updated, related[]) + a markdown body carrying plain
`[[wikilinks]]`. No capstone code was consulted or ported (DECISION_LOG D2).
"""

import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import yaml

TYPE_DEFAULT = "concept"
SENSITIVITIES = ("normal", "work")

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class OKFError(ValueError):
    """A one-line reason the text is not a valid OKF concept."""


def slugify(text: str) -> str:
    """Deterministic slug: NFKD-folded, lowercase, alnum runs joined by hyphens."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    if not slug:
        raise OKFError(f"cannot derive a slug from {text!r}")
    return slug


def now_stamp() -> str:
    forced = os.environ.get("MEM_NOW")  # test seam: freeze the clock
    if forced:
        return forced
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Concept:
    slug: str
    title: str
    description: str
    type: str
    topics: list
    sensitivity: str
    created: str
    updated: str
    related: list = field(default_factory=list)
    body: str = ""

    def validate(self) -> "Concept":
        if not _SLUG_RE.match(self.slug):
            raise OKFError(f"invalid slug {self.slug!r} (lowercase alnum-hyphen)")
        for name in ("title", "description", "created", "updated"):
            if not str(getattr(self, name)).strip():
                raise OKFError(f"missing required field: {name}")
        if not self.type.strip():
            raise OKFError("missing required field: type")
        if self.sensitivity not in SENSITIVITIES:
            raise OKFError(
                f"invalid sensitivity {self.sensitivity!r} (one of: {', '.join(SENSITIVITIES)})"
            )
        for name in ("topics", "related"):
            items = getattr(self, name)
            if not isinstance(items, list) or not all(
                isinstance(i, str) and i.strip() for i in items
            ):
                raise OKFError(f"{name} must be a list of non-empty strings")
        if not self.body.strip():
            raise OKFError("empty body")
        return self

    def to_dict(self) -> dict:
        data = asdict(self)
        data["id"] = self.slug  # id and slug are the same key, emitted under both names
        return data


def serialize(concept: Concept) -> str:
    concept.validate()
    front = {
        "id": concept.slug,
        "slug": concept.slug,
        "title": concept.title,
        "description": concept.description,
        "type": concept.type,
        "topics": list(concept.topics),
        "sensitivity": concept.sensitivity,
        "created": concept.created,
        "updated": concept.updated,
        "related": list(concept.related),
    }
    yaml_text = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{yaml_text}---\n\n{concept.body.rstrip()}\n"


def _as_str(value) -> str:
    if isinstance(value, datetime):  # externally-edited frontmatter may use bare timestamps
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "" if value is None else str(value)


def _as_str_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise OKFError(f"expected a list, got {type(value).__name__}")


def parse(text: str) -> Concept:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise OKFError("no YAML frontmatter block")
    try:
        front = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        reason = str(e).splitlines()[0]
        raise OKFError(f"unparseable frontmatter: {reason}") from e
    if not isinstance(front, dict):
        raise OKFError("frontmatter is not a mapping")
    slug = _as_str(front.get("slug") or front.get("id"))
    return Concept(
        slug=slug,
        title=_as_str(front.get("title")),
        description=_as_str(front.get("description")),
        type=_as_str(front.get("type")) or TYPE_DEFAULT,
        topics=_as_str_list(front.get("topics")),
        sensitivity=_as_str(front.get("sensitivity")) or "normal",
        created=_as_str(front.get("created")),
        updated=_as_str(front.get("updated")),
        related=_as_str_list(front.get("related")),
        body=match.group(2).lstrip("\n"),
    ).validate()
