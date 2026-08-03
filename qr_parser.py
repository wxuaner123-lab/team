from __future__ import annotations

from io import BytesIO
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps


def image_bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def decode_qr_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Decode QR content from a camera/uploaded image with OpenCV.

    Returns a rule-based result. It intentionally avoids cloud calls so the
    factory terminal can keep working on an intranet.
    """
    image = image_bytes_to_cv2(image_bytes)
    detector = cv2.QRCodeDetector()

    decoded_values: list[str] = []
    points_count = 0

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
        if ok and decoded_info:
            decoded_values = [value for value in decoded_info if value]
            points_count = 0 if points is None else len(points)
    except Exception:
        decoded_values = []

    if not decoded_values:
        value, points, _ = detector.detectAndDecode(image)
        if value:
            decoded_values = [value]
            points_count = 0 if points is None else 1

    return {
        "success": bool(decoded_values),
        "values": decoded_values,
        "text": decoded_values[0] if decoded_values else "",
        "qr_count": points_count,
        "message": "二维码识别成功" if decoded_values else "未识别到二维码，请重拍或手动输入。",
    }
