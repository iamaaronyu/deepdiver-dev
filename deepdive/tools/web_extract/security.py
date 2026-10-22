"""Normalize targets, validate every DNS answer, and pin connections to a checked address."""
import asyncio
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from deepdive.tools.search.models import ToolFailure

TRANSITION_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))


def normalize_url(value: str) -> str:
    try:
        if not value or len(value) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError()
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if parts.scheme not in ("https", "http") or not host or parts.username is not None or parts.password is not None:
            raise ValueError()
        if parts.port not in (None, 443 if parts.scheme == "https" else 80):
            raise ValueError()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "%" in host:
            raise ValueError()
        authority = "[" + host + "]" if ":" in host else host
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                           if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}])
        return urlunsplit((parts.scheme, authority, parts.path or "/", query, ""))
    except (ValueError, UnicodeError):
        raise ToolFailure("unsafe_url", "URL 协议、主机或端口不允许访问。") from None


def public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global or address.is_multicast or address.is_reserved:
            return False
        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped or any(address in network for network in TRANSITION_NETWORKS):
                return False
        return True
    except ValueError:
        return False


async def resolve_public(host: str, port: int) -> str:
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            raise ToolFailure("dns_failed", "来源域名解析失败。") from None
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or not all(public_address(address) for address in addresses):
        raise ToolFailure("unsafe_address", "来源解析到本机、私有或不允许的网络地址。")
    return next((address for address in addresses if ":" not in address), addresses[0])
