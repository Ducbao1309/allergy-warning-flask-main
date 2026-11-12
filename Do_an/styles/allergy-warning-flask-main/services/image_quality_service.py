"""Local, dependency-light checks for uploaded product-label images."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


MIN_SHORT_SIDE = 400
BLUR_THRESHOLD = 30.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ANALYSIS_DIMENSION = 512
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass(frozen=True)
class ImageQualityResult:
    is_valid: bool
    score: float | None
    reasons: tuple[str, ...]
    message: str
    width: int | None = None
    height: int | None = None


def _laplacian_variance(gray_image):
    """Estimate sharpness with the variance of a four-neighbor Laplacian."""
    analysis_image = gray_image.copy()
    analysis_image.thumbnail((MAX_ANALYSIS_DIMENSION, MAX_ANALYSIS_DIMENSION), Image.Resampling.LANCZOS)
    pixels = analysis_image.load()
    width, height = analysis_image.size
    count = 0
    total = 0.0
    total_squared = 0.0

    for y in range(1, height - 1):
        for x in range(1, width - 1):
            center = pixels[x, y]
            laplacian = (
                4 * center
                - pixels[x - 1, y]
                - pixels[x + 1, y]
                - pixels[x, y - 1]
                - pixels[x, y + 1]
            )
            total += laplacian
            total_squared += laplacian * laplacian
            count += 1

    if not count:
        return 0.0
    mean = total / count
    return max(0.0, total_squared / count - mean * mean)


def _failed_result(reason, score=None, width=None, height=None):
    return ImageQualityResult(
        is_valid=False,
        score=score,
        reasons=(reason,),
        message=reason,
        width=width,
        height=height,
    )


def check_image_quality(image_path):
    """Validate the file, decoded format, resolution, and focus before Gemini."""
    path = Path(image_path)
    try:
        if not path.is_file():
            return _failed_result("Không thể đọc ảnh. Vui lòng chọn lại ảnh.")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            return _failed_result("Ảnh vượt quá giới hạn tải lên. Vui lòng chọn ảnh nhỏ hơn.")
    except OSError:
        return _failed_result("Không thể đọc ảnh. Vui lòng chọn lại ảnh.")

    try:
        with Image.open(path) as opened_image:
            image_format = opened_image.format
            opened_image.verify()
        if image_format not in SUPPORTED_FORMATS:
            return _failed_result("Định dạng ảnh không được hỗ trợ. Vui lòng chọn JPG, PNG hoặc WEBP.")

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            width, height = image.size
            gray = image.convert("L")
    except Exception:
        return _failed_result("Không thể đọc ảnh. Vui lòng chọn lại ảnh.")

    short_side = min(width, height)
    if short_side < MIN_SHORT_SIDE:
        return _failed_result(
            f"Ảnh có độ phân giải quá thấp ({width} × {height}; cạnh ngắn {short_side} px). "
            "Vui lòng chụp gần nhãn sản phẩm hơn.",
            width=width,
            height=height,
        )

    score = _laplacian_variance(gray)
    if score < BLUR_THRESHOLD:
        return _failed_result(
            f"Ảnh có vẻ bị mờ (điểm độ nét {score:.1f}). "
            "Vui lòng giữ điện thoại ổn định và chụp lại nhãn sản phẩm.",
            score=score,
            width=width,
            height=height,
        )

    return ImageQualityResult(
        is_valid=True,
        score=score,
        reasons=(),
        message="Ảnh đạt yêu cầu chất lượng.",
        width=width,
        height=height,
    )
