"""Byte-level integrity and image checks, without claiming redaction or clearance."""
import base64
import hashlib
from io import BytesIO

from PIL import Image, UnidentifiedImageError


def verify_jpeg(data, *, sha256=None, size_bytes=None):
    if not data or len(data) > 524288:
        raise ValueError("JPEG must contain 1–524288 bytes")
    if size_bytes is not None and len(data) != size_bytes:
        raise ValueError("Image size does not match upload declaration")
    digest = hashlib.sha256(data).hexdigest()
    if sha256 is not None and digest != sha256:
        raise ValueError("Image checksum does not match upload declaration")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG" or image.width * image.height > 20000000:
                raise ValueError("Expected JPEG up to 20 megapixels")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or oversized JPEG image") from exc
    return digest


def upload_headers(size_bytes, sha256):
    return {"Content-Type": "image/jpeg", "Content-Length": str(size_bytes),
            "If-None-Match": "*", "x-amz-server-side-encryption": "AES256",
            "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha256)).decode()}
