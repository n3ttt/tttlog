from pathlib import Path

from tttlog.core.cluster import (Home, describe_filter, detect_cluster_kind, filter_commands,
                                 parse_spot, spot_passes, spotter_base)

HOME = Home(zone=5, cont="NA", country="United States", prefix="K")


def spot(spotter, zone, cont="NA", country="United States", skimmer=False):
    s = parse_spot(f"DX de {spotter}:     14025.0  DL1ABC       CQ           1234Z")
    s.spotter_zone, s.spotter_cont, s.spotter_country, s.skimmer = zone, cont, country, skimmer
    return s


def test_skimmer_detected():
    rbn = parse_spot("DX de K1TTT-#:     14025.0  DL1ABC       CW 23 dB 28 WPM CQ      1234Z")
    human = parse_spot("DX de W3LPL:     14205.0  DL1ABC       59 loud           1234Z")
    assert rbn.skimmer and rbn.spotter == "K1TTT" and not human.skimmer
    assert parse_spot("DX de W1NT-6:   7025.0  DL1ABC   CW 12 dB 25 WPM CQ  0001Z").skimmer
    assert spotter_base("W3LPL-2") == "W3LPL" and spotter_base("K1TTT-#") == "K1TTT"


def test_local_filter():
    near, far = spot("W3LPL", 5), spot("W6XX", 3)
    eu = spot("DL1AA", 14, "EU", "Fed. Rep. of Germany")
    sk = spot("K1TTT", 5, skimmer=True)
    unknown = spot("XX9XX", None)
    f = {"spotters": "zone", "skimmer": "all"}
    assert [spot_passes(s, f, HOME) for s in (near, far, eu, sk, unknown)] == [True, False, False, True, True]
    f = {"spotters": "cont", "skimmer": "no"}
    assert [spot_passes(s, f, HOME) for s in (near, far, eu, sk)] == [True, True, False, False]
    f = {"spotters": "any", "skimmer": "only"}
    assert [spot_passes(s, f, HOME) for s in (near, sk)] == [False, True]
    f = {"spotters": "zones", "zones": [3, 4], "skimmer": "all"}
    assert [spot_passes(s, f, HOME) for s in (near, far)] == [False, True]
    assert describe_filter({"spotters": "zone", "skimmer": "no"}, HOME) == "spotters in zone 5, no skimmers"
    assert describe_filter({"spotters": "any", "skimmer": "all"}, HOME) == ""


def test_cluster_filter_commands():
    zone_noskim = {"spotters": "zone", "skimmer": "no"}
    assert filter_commands("ar", zone_noskim, HOME)[0] == ["set dx filter SpotterCqZone=5 and not skimmer"]
    assert filter_commands("ar", {"spotters": "any", "skimmer": "all"}, HOME)[0] == ["set dx filter"]
    assert filter_commands("ar", {"spotters": "zones", "zones": [4, 5], "skimmer": "all"}, HOME)[0] == \
        ["set dx filter (SpotterCqZone=4 or SpotterCqZone=5)"]
    assert filter_commands("ar", {"spotters": "cont", "skimmer": "only"}, HOME)[0] == \
        ["set dx filter SpotterCont=NA and skimmer"]
    assert filter_commands("spider", zone_noskim, HOME)[0] == \
        ["clear/spots all", "accept/spots by_zone 5", "unset/skimmer"]
    cmds, notes = filter_commands("cc", zone_noskim, HOME)
    assert cmds == ["set/filter doc/off", "set/noskimmer"] and notes          # CC: zone stays local
    assert filter_commands("cc", {"spotters": "country", "skimmer": "all"}, HOME)[0] == \
        ["set/filter doc/pass K", "set/skimmer"]
    assert filter_commands("", zone_noskim, HOME) == ([], [filter_commands("", zone_noskim, HOME)[1][0]])


def test_detect_cluster_kind():
    assert detect_cluster_kind("Welcome to W3LPL AR-Cluster node Telnet port 7373") == "ar"
    assert detect_cluster_kind("Hello N3TTT, this is VE7CC-1 in Maple Ridge, running CC Cluster") == "cc"
    assert detect_cluster_kind("Hello N3TTT, this is GB7MBC running DXSpider V1.57") == "spider"
    assert detect_cluster_kind("DX de W3LPL: 14025.0 DL1ABC") == ""
