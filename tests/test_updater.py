from tttlog import __version__
from tttlog import updater


def test_version_compare():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("0.2") == (0, 2, 0)
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer("0.2.0", "0.2.0")
    assert not updater.is_newer("0.1.9", "0.2.0")
    assert updater.is_newer("1.0.0-beta", "0.9.0")


def test_version_string():
    assert updater.version_string().startswith(__version__)


def test_asset_suffix():
    assert updater.platform_asset_suffix().endswith((".dmg", ".zip", ".tar.gz"))
