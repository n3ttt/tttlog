import pytest

from tttlog import config


@pytest.fixture(autouse=True)
def _no_real_network_settings(tmp_path, monkeypatch):
    """Tests never read or write the real ~/.tttlog network files."""
    monkeypatch.setattr(config, "NETWORK_FILE", tmp_path / "net-cfg" / "network.yaml")
    monkeypatch.setattr(config, "NODE_ID_FILE", tmp_path / "net-cfg" / "node_id")
    monkeypatch.setattr(config, "WSJTX_FILE", tmp_path / "net-cfg" / "wsjtx.yaml")
    monkeypatch.setattr(config, "RIG_FILE", tmp_path / "net-cfg" / "radio.yaml")
    monkeypatch.setattr(config, "KEYER_FILE", tmp_path / "net-cfg" / "keyer.yaml")
    monkeypatch.setattr(config, "N1MM_FILE", tmp_path / "net-cfg" / "n1mm.yaml")
    monkeypatch.setattr(config, "CALLBOOK_FILE", tmp_path / "net-cfg" / "callbook.yaml")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
