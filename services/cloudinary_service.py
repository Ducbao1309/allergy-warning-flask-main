
import os
import cloudinary
import cloudinary.uploader


def upload_scan_image(image_path):
    """
    Upload ảnh quét lên Cloudinary.
    Trả về URL HTTPS để lưu vào database.
    """

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        raise RuntimeError("Cloudinary chưa được cấu hình đầy đủ.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

    if not os.path.isfile(image_path):
        raise FileNotFoundError("Không tìm thấy ảnh cần upload.")

    result = cloudinary.uploader.upload(
        image_path,
        folder="allergy-warning/scans",
        resource_type="image"
    )

    image_url = result.get("secure_url")

    if not image_url:
        raise RuntimeError("Cloudinary không trả về URL ảnh.")

    return image_url
