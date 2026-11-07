import pytest

from app.devices import network


def test_parse_claim_valid_dedupes_local_ips() -> None:
    info = network.parse_claim(
        {
            "v": 1,
            "public_ip": "203.0.113.7",
            "local_ips": ["192.168.1.5", "192.168.1.5", "10.0.0.2"],
        }
    )
    assert info.public_ip == "203.0.113.7"
    assert info.local_ips == ("192.168.1.5", "10.0.0.2")


def test_parse_claim_accepts_ipv6() -> None:
    info = network.parse_claim({"v": 1, "public_ip": "2001:db8::1"})
    assert info.public_ip == "2001:db8::1"
    assert info.local_ips == ()


def test_parse_claim_public_ip_may_be_absent_or_null() -> None:
    assert network.parse_claim({"v": 1, "local_ips": []}).public_ip is None
    assert network.parse_claim({"v": 1, "public_ip": None}).public_ip is None


def test_parse_claim_rejects_bad_ip() -> None:
    with pytest.raises(network.InvalidNetwork):
        network.parse_claim({"v": 1, "public_ip": "not-an-ip"})


def test_parse_claim_rejects_wrong_version() -> None:
    with pytest.raises(network.InvalidNetwork):
        network.parse_claim({"v": 2, "public_ip": "203.0.113.7"})


def test_parse_claim_rejects_extra_keys() -> None:
    with pytest.raises(network.InvalidNetwork):
        network.parse_claim({"v": 1, "public_ip": "203.0.113.7", "mac": "aa:bb"})


def test_parse_claim_rejects_too_many_local_ips() -> None:
    with pytest.raises(network.InvalidNetwork):
        network.parse_claim({"v": 1, "local_ips": [f"10.0.0.{i}" for i in range(20)]})


def test_parse_claim_rejects_non_dict() -> None:
    with pytest.raises(network.InvalidNetwork):
        network.parse_claim(["not", "a", "dict"])
