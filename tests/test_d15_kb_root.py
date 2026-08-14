"""D15 - MEM_KB_ROOT routes the whole CLI at an alternate KB instance.

Invariants: (1) each instance resolves its own content and NOT the other's,
with BOTH KB homes existing during the negative checks (so failure demonstrates
isolation, not a missing home); (2) blank/whitespace override falls back to the
default root; (3) ~ expands. Daemon stays down throughout (degraded-but-working
writes, F2: save lands).
"""

import json


def _save(mem, title, body, env_extra=None):
    r = mem("save", "--title", title, "--body", body,
            "--description", f"{title} probe", "--topics", "d15",
            env_extra=env_extra)
    assert r.returncode == 0, r.stderr


def test_two_instances_isolate_both_ways(kb, mem):
    alt = kb.home / "personal-kb"
    over = {"MEM_KB_ROOT": str(alt)}

    r = mem("init", env_extra=over)
    assert r.returncode == 0, r.stderr
    assert alt.is_dir() and (alt / ".git").is_dir()
    assert not kb.kb.exists(), "default root must be untouched by an override init"

    r = mem("init")
    assert r.returncode == 0, r.stderr
    assert kb.kb.is_dir(), "no override -> default ~/.agent-memory"

    _save(mem, "Alt instance probe", "Lands only in the override instance.",
          env_extra=over)
    _save(mem, "Default instance probe", "Lands only in the default instance.")

    # each route resolves its own concept...
    r = mem("get", "alt-instance-probe", "--json", env_extra=over)
    assert r.returncode == 0, r.stderr
    assert str(alt) in json.loads(r.stdout)["path"]
    r = mem("get", "default-instance-probe", "--json")
    assert r.returncode == 0, r.stderr
    assert str(kb.kb) in json.loads(r.stdout)["path"]

    # ...and NOT the other's, with both KB homes present
    r = mem("get", "alt-instance-probe", "--json")
    assert r.returncode != 0, "alt content must be invisible via the default route"
    r = mem("get", "default-instance-probe", "--json", env_extra=over)
    assert r.returncode != 0, "default content must be invisible via the override route"


def test_blank_and_whitespace_override_fall_back_to_default(kb, mem):
    r = mem("init", env_extra={"MEM_KB_ROOT": ""})
    assert r.returncode == 0, r.stderr
    assert kb.kb.is_dir(), "blank override -> default root"

    _save(mem, "Fallback probe", "Default-root save under whitespace override.",
          env_extra={"MEM_KB_ROOT": " \t "})
    r = mem("get", "fallback-probe", "--json", env_extra={"MEM_KB_ROOT": " \t "})
    assert r.returncode == 0, r.stderr
    assert str(kb.kb) in json.loads(r.stdout)["path"]
    assert not (kb.home / " \t ").exists()


def test_tilde_expansion(kb, mem):
    over = {"MEM_KB_ROOT": "~/personal-kb"}
    r = mem("init", env_extra=over)
    assert r.returncode == 0, r.stderr
    _save(mem, "Tilde probe", "Saved through a tilde-relative root.", env_extra=over)
    r = mem("get", "tilde-probe", "--json", env_extra=over)
    assert r.returncode == 0, r.stderr
    assert str(kb.home / "personal-kb") in json.loads(r.stdout)["path"]
