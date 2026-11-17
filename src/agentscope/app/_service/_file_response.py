# -*- coding: utf-8 -*-
"""One browser policy for all user-controlled file responses."""

from urllib.parse import quote

INLINE_TYPES = {
    "application/pdf",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "audio/mpeg",
    "audio/wav",
    "video/mp4",
}


def file_headers(
    filename: str, media_type: str, download: bool
) -> dict[str, str]:
    disposition = (
        "inline"
        if not download and media_type in INLINE_TYPES
        else "attachment"
    )
    return {
        "Content-Disposition": (
            f"{disposition}; filename*=UTF-8''{quote(filename)}"
        ),
        "Content-Security-Policy": (
            "sandbox; default-src 'none'; base-uri 'none'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
