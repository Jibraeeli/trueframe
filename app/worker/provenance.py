"""Check 1: does the file carry C2PA content credentials?

Content credentials are a signed record of how a file was made. Three different
things can be true, and they must not be confused:

- Trusted: signed by someone on a trust list, and the file is unchanged.
- Signed but untrusted: the file is unchanged, but anyone can create a signature
  like this, so it earns no extra trust.
- Invalid: the file changed after signing.

Stage 1 has no trust list configured, so real files report as signed but
untrusted. Most files have no credentials at all, which proves nothing.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import c2pa

TRUSTED = "trusted"
SIGNED_UNTRUSTED = "signed_untrusted"
INVALID = "invalid"
NONE = "none"
NOT_SUPPORTED = "not_supported"

_AI_SOURCE_TYPES = ("trainedalgorithmicmedia", "compositewithtrainedalgorithmicmedia")

# A file can name a web address for its credentials. Uploads are untrusted, so
# the worker must never be tricked into requesting an address chosen by a user.
_READER_SETTINGS = {"verify": {"remote_manifest_fetch": False}}


@dataclass
class ProvenanceResult:
    status: str
    note: str
    ai_generated: bool = False
    issuer: str | None = None
    claim_generator: str | None = None


def declares_ai(manifest: dict) -> bool:
    """Look for an AI source type in the manifest's list of actions."""
    for assertion in manifest.get("assertions", []):
        if not str(assertion.get("label", "")).startswith("c2pa.actions"):
            continue
        for action in assertion.get("data", {}).get("actions", []):
            source_type = str(action.get("digitalSourceType", "")).lower()
            if source_type.endswith(_AI_SOURCE_TYPES):
                return True
    return False


def summarise(state: str | None, store: dict) -> ProvenanceResult:
    manifest = store.get("manifests", {}).get(store.get("active_manifest"), {})
    issuer = manifest.get("signature_info", {}).get("issuer")
    generator = manifest.get("claim_generator")

    if state == "Invalid":
        return ProvenanceResult(
            INVALID, "Credentials failed validation.", False, issuer, generator
        )
    ai_generated = declares_ai(manifest)
    if state == "Trusted":
        return ProvenanceResult(
            TRUSTED, f"Signed by {issuer}.", ai_generated, issuer, generator
        )
    return ProvenanceResult(
        SIGNED_UNTRUSTED,
        f"Signed by {issuer}, but that signer is not on a trust list, so this adds no trust.",
        ai_generated,
        issuer,
        generator,
    )


def check(path: Path, media_type: str) -> ProvenanceResult:
    try:
        with c2pa.Context.from_dict(_READER_SETTINGS) as context, path.open("rb") as stream:
            with c2pa.Reader(media_type, stream, context=context) as reader:
                return summarise(reader.get_validation_state(), json.loads(reader.json()))
    except c2pa.C2paError.ManifestNotFound:
        return ProvenanceResult(NONE, "No content credentials. Most files do not have them.")
    except c2pa.C2paError.NotSupported:
        return ProvenanceResult(NOT_SUPPORTED, "Content credentials cannot be read for this format.")
    except c2pa.C2paError:
        return ProvenanceResult(INVALID, "Credentials are present but could not be read.")
