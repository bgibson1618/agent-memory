from types import SimpleNamespace
from unittest.mock import patch

from agent_memory import initcmd


def test_shared_init_does_not_modify_source_or_guidance(tmp_path):
    with patch("agent_memory.config.kb_root", return_value=tmp_path), \
         patch("agent_memory.shared.profile_for", return_value={"machine": "host"}), \
         patch("agent_memory.blocks.install") as install:
        assert initcmd.cmd_init(SimpleNamespace()) == 1
    assert list(tmp_path.iterdir()) == []
    install.assert_not_called()
