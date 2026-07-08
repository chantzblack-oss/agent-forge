"""Real photography — fetch openly-licensed images from Wikimedia Commons.

A diagram explains; a photograph testifies. When a scene is about a real
person, place, machine, or event, the script names it and this module
finds an actual photo (Commons hosts freely-licensed media; we render the
credit on screen).
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

_UA = {"User-Agent": "AgentForge/1.0 (personal learning feed)"}


def _ctx():
    cert = os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"
    if os.path.exists(cert):
        return ssl.create_default_context(cafile=cert)
    return None


def find_photo(query: str, out_path: str | Path) -> dict | None:
    """Search Commons for `query`, download the best hit to out_path.
    Returns {'path', 'credit'} or None (scene degrades to no photo)."""
    try:
        api = ("https://commons.wikimedia.org/w/api.php?action=query"
               "&format=json&generator=search&gsrnamespace=6&gsrlimit=6"
               "&gsrsearch=" + urllib.parse.quote(f"filetype:bitmap {query}")
               + "&prop=imageinfo&iiprop=url|size|extmetadata"
                 "&iiurlwidth=1400")
        req = urllib.request.Request(api, headers=_UA)
        with urllib.request.urlopen(req, timeout=12, context=_ctx()) as r:
            data = json.load(r)
        pages = (data.get("query") or {}).get("pages") or {}
        best = None
        for p in sorted(pages.values(), key=lambda p: p.get("index", 9)):
            ii = (p.get("imageinfo") or [{}])[0]
            if ii.get("width", 0) >= 700 and ii.get("thumburl"):
                best = ii
                break
        if best is None:
            return None
        meta = best.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "",
                        (meta.get("Artist") or {}).get("value", "")).strip()[:60]
        lic = ((meta.get("LicenseShortName") or {}).get("value", "") or "")[:24]
        req2 = urllib.request.Request(best["thumburl"], headers=_UA)
        out_path = Path(out_path)
        with urllib.request.urlopen(req2, timeout=25, context=_ctx()) as r:
            out_path.write_bytes(r.read())
        if out_path.stat().st_size < 10000:
            return None
        credit = " · ".join(x for x in (artist, lic) if x)
        return {"path": out_path, "credit": credit or "Wikimedia Commons"}
    except Exception:
        return None
