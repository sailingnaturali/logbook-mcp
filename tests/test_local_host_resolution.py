"""mDNS .local hosts hang httpx's async connect on macOS; LogbookClient resolves
a .local host to IPv4 at construction. (Mirrors signalk-mcp's fix.)"""
import socket
from unittest.mock import patch

from logbook_mcp.client import LogbookClient


def _fake_getaddrinfo(ip):
    def _f(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
    return _f


def test_local_host_resolved_to_ipv4():
    with patch("logbook_mcp.client.socket.getaddrinfo",
               _fake_getaddrinfo("192.168.68.60")):
        c = LogbookClient("http://naturalaspi.local:3000")
    assert c.base_url == "http://192.168.68.60:3000"


def test_non_local_host_unchanged():
    assert LogbookClient("http://192.168.68.60:3000").base_url == \
        "http://192.168.68.60:3000"


def test_local_resolution_failure_falls_back():
    def _boom(*a, **k):
        raise socket.gaierror("no resolve")
    with patch("logbook_mcp.client.socket.getaddrinfo", _boom):
        c = LogbookClient("http://naturalaspi.local:3000")
    assert c.base_url == "http://naturalaspi.local:3000"
