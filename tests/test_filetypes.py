import pytest

from app.api.filetypes import sniff


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypmp42rest", "video/mp4"),
        (b"\x00\x00\x00\x14ftypqt  rest", "video/quicktime"),
        (b"\x1a\x45\xdf\xa3rest", "video/webm"),
    ],
)
def test_allowed_formats(header, expected):
    assert sniff(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        b"",
        b"MZ\x90\x00 an exe",
        b"%PDF-1.7",
        b"<html><script>",
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
        b"\x00\x00\x00\x18ftypheic",
        b"\x00\x00\x00\x18ftypM4A ",
    ],
)
def test_everything_else_is_refused(header):
    assert sniff(header) is None
