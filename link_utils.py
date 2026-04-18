from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


@dataclass(frozen=True)
class SharedLinkResult:
    url: str
    reused: bool


def to_direct_stream_url(shared_link_url: str) -> str:
    parsed = urlparse(shared_link_url)

    host = parsed.netloc
    if host == "www.dropbox.com":
        host = "dl.dropboxusercontent.com"

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "raw" in query:
        query["raw"] = "1"
    else:
        query["dl"] = "1"

    rebuilt = parsed._replace(netloc=host, query=urlencode(query))
    return urlunparse(rebuilt)


def get_or_create_shared_link(dbx, path: str, *, direct_only: bool = True) -> SharedLinkResult:
    links = dbx.sharing_list_shared_links(path=path, direct_only=direct_only).links
    if links:
        return SharedLinkResult(url=links[0].url, reused=True)

    link = dbx.sharing_create_shared_link_with_settings(path)
    return SharedLinkResult(url=link.url, reused=False)
