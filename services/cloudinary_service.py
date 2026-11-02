import os
import logging
import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)


def upload_scan_image(image_path):
    """
    Upload ảnh quét lên Cloudinary.
    Trả về URL HTTPS để lưu vào database.
    Giới hạn thời gian chờ để tránh request bị treo.
    """

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        raise RuntimeError(
            "Cloudinary chưa được cấu hình đầy đủ."
        )

    if not os.path.isfile(image_path):
        raise FileNotFoundError(
            "Không tìm thấy ảnh cần upload."
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

    try:
        result = cloudinary.uploader.upload(
            image_path,
            folder="allergy-warning/scans",
            resource_type="image",
            timeout=45
        )

        image_url = result.get("secure_url")

        if not image_url:
            raise RuntimeError(
                "Cloudinary không trả về URL ảnh."
            )

        logger.info(
            "Cloudinary upload successful."
        )

        return image_url

    except Exception:
        logger.exception(
            "Cloudinary upload failed."
        )
        raise