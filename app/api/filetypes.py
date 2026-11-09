"""Work out what a file really is from its first bytes.

The filename and the browser's content type are both supplied by the user, so
neither can be trusted. File formats start with a fixed signature, so we check
that instead and refuse anything not on the list.
"""

HEADER_BYTES = 32

# These formats use the same container as MP4 but are not video we can analyse.
_NON_VIDEO_BRANDS = {b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"M4A ", b"M4B "}


def sniff(header: bytes) -> str | None:
    """Return the media type for a file header, or None if it is not allowed."""
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in _NON_VIDEO_BRANDS:
            return None
        return "video/quicktime" if brand == b"qt  " else "video/mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None
