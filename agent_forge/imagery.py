"""Generated cinematic imagery — every scene can be a painted shot.

The template (text + charts + silhouettes) has a ceiling: it reads as
design, not film. This module renders bespoke scene art from the script's
shot descriptions using the OpenAI image models, in one consistent
editorial style, so an episode looks illustrated end to end.
"""

from __future__ import annotations

import base64
import os
import ssl
import urllib.request
from pathlib import Path

# One house style, appended to every shot description — scenes cohere
# across the episode instead of looking like eight different artists.
_HOUSE_STYLE = (
    ", cinematic minimalist editorial illustration, moody atmospheric "
    "lighting, dark slate and deep teal palette with a single warm amber "
    "accent, subtle film grain, painterly, high detail, vertical "
    "composition, no text, no words, no captions, no watermark")


def generate_image(prompt: str, out_path: str | Path) -> bool:
    """Render one scene illustration. Returns False on any failure so the
    scene degrades to the template."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    if os.environ.get("FORGE_IMAGERY", "1") == "0":
        return False
    from openai import OpenAI
    client = OpenAI()
    out_path = Path(out_path)
    full = prompt.strip()[:800] + _HOUSE_STYLE
    attempts = (
        ("gpt-image-1", "1024x1536", {"quality": "medium"}),
        ("dall-e-3", "1024x1792", {"quality": "standard"}),
    )
    for model, size, kw in attempts:
        try:
            r = client.images.generate(model=model, prompt=full,
                                       size=size, n=1, **kw)
            d = r.data[0]
            if getattr(d, "b64_json", None):
                out_path.write_bytes(base64.b64decode(d.b64_json))
            elif getattr(d, "url", None):
                cert = (os.environ.get("SSL_CERT_FILE")
                        or "/root/.ccr/ca-bundle.crt")
                ctx = (ssl.create_default_context(cafile=cert)
                       if os.path.exists(cert) else None)
                with urllib.request.urlopen(d.url, timeout=60,
                                            context=ctx) as resp:
                    out_path.write_bytes(resp.read())
            else:
                continue
            if out_path.stat().st_size > 20000:
                return True
        except Exception:
            continue
    return False
