"""LogbookClient resolves a .local host to IPv4 at construction (via the shared
naturali-mcp-netutil helper). Helper logic is tested upstream; here we prove the
client wires it."""
import socket
from unittest.mock import patch

from logbook_mcp.client import LogbookClient


def _fake_getaddrinfo(ip):
    def _f(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    return _f


def test_client_resolves_local_host_to_ipv4():
    with patch("naturali_mcp_netutil.host.socket.getaddrinfo",
               _fake_getaddrinfo("192.168.68.60")):
        c = LogbookClient("http://naturalaspi.local:3000")
    assert c.base_url == "http://192.168.68.60:3000"


def test_client_non_local_host_unchanged():
    assert LogbookClient("http://192.168.68.60:3000").base_url == \
        "http://192.168.68.60:3000"
