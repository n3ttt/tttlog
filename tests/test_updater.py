from tttlog import __version__, updater


def test_version_order():
    pv = updater.parse_version
    assert pv("v0.1.0a3") == (0, 1, 0, 0, 3)
    assert pv("0.1.0a3") > pv("0.1.0a2")
    assert pv("0.1.0b1") > pv("0.1.0a9")
    assert pv("0.1.0") > pv("0.1.0rc2")
    assert pv("0.2") > pv("0.1.9")
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer(__version__)


def test_pick_latest_includes_prereleases_and_matches_asset():
    rels = [
        {"tag_name": "v0.1.0a2", "assets": [], "html_url": "u2"},
        {"tag_name": "v0.1.0a3", "html_url": "u3", "body": "notes",
         "assets": [{"name": "tttlog-0.1.0a3-macos-arm64.dmg", "browser_download_url": "d1"},
                    {"name": "tttlog-0.1.0a3-windows.zip", "browser_download_url": "d2"}]},
        {"tag_name": "v9.9.9", "draft": True, "assets": []},
    ]
    r = updater.pick_latest(rels, "macos-arm64.dmg")
    assert (r.version, r.asset_url, r.notes) == ("0.1.0a3", "d1", "notes")
    assert updater.pick_latest(rels, "linux-x86_64.tar.gz").asset_url is None


def test_version_string():
    assert updater.version_string().startswith(__version__)


def test_mac_asset_is_arm64_under_rosetta(monkeypatch):
    """The Intel build under Rosetta must still update to the Apple Silicon build."""
    from tttlog import updater
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(updater, "_sysctl", lambda n: {"hw.optional.arm64": "1",
                                                        "sysctl.proc_translated": "1"}.get(n, ""))
    assert updater.platform_asset_suffix() == "macos-arm64.dmg" and updater.running_under_rosetta()
    monkeypatch.setattr(updater, "_sysctl", lambda n: "")          # a real Intel Mac
    assert updater.platform_asset_suffix() == "macos-x86_64.dmg" and not updater.running_under_rosetta()
