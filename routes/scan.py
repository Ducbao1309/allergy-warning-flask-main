import os
import uuid
import logging
import inspect

from functools import wraps
from itsdangerous import (
    BadSignature,
    SignatureExpired,
    URLSafeTimedSerializer,
)

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    current_app,
    flash,
)

from werkzeug.exceptions import RequestEntityTooLarge
from sqlalchemy.exc import SQLAlchemyError

from extensions import db

from services.gemini_service import (
    GeminiConfigurationError,
    GeminiServiceError,
    InvalidProductImageError,
    analyze_product_image,
)

from services.product_service import (
    find_product_by_identity,
    save_scanned_product,
    get_product_ingredients,
    get_product_allergens,
    check_product_ingredients,
    should_mark_allergen_result_unknown,
    normalize_and_deduplicate_ingredients,
)

from models import UserAllergen, ScanHistory

from services.history_service import (
    save_scan_history,
    attach_product_to_scan_history,
)


logger = logging.getLogger(__name__)

SCAN_SAVE_SALT = "scan-save-product-v1"


# =========================================================
# FATAL ERROR LOGGER
# =========================================================

def _log_scan_fatal(view_function):

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        try:
            return view_function(*args, **kwargs)

        except Exception as error:

            current_app.logger.error(
                "[SCAN FATAL] exception_type=%s exception=%s",
                type(error).__name__,
                error,
            )

            current_app.logger.exception(
                "[SCAN FATAL] unhandled exception in process_scan"
            )

            raise

    return wrapped_view


# =========================================================
# BLUEPRINT
# =========================================================

scan_bp = Blueprint(
    "scan",
    __name__,
    url_prefix="/scan",
)


# =========================================================
# UPLOAD ERROR
# =========================================================

@scan_bp.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):

    flash(
        "Ảnh vượt quá giới hạn tải lên 10 MB. "
        "Vui lòng chọn ảnh nhỏ hơn.",
        "error",
    )

    return render_template("scan.html"), 413


# =========================================================
# TRANG QUÉT
# =========================================================

@scan_bp.route("/")
def scan_page():

    if "user_id" not in session:
        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "scan.html",
        scan_request_id=uuid.uuid4().hex,
    )


# =========================================================
# DEBUG UPLOAD
# =========================================================

@scan_bp.route("/debug-upload")
def debug_upload_page():

    if "user_id" not in session:
        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "scan_debug_upload.html"
    )


# =========================================================
# XỬ LÝ ẢNH
# =========================================================

@scan_bp.route(
    "/process",
    methods=["POST"],
)
@_log_scan_fatal
def process_scan():

    current_app.logger.info(
        "[SCAN STAGE 1] process_scan entered"
    )

    current_app.logger.info(
        "[SCAN DEBUG] POST /scan/process RECEIVED"
    )

    current_app.logger.info(
        "[SCAN DEBUG] files=%s",
        list(request.files.keys()),
    )

    uploaded_file = request.files.get("image")

    current_app.logger.info(
        "[SCAN STAGE 2] uploaded_file received"
    )

    current_app.logger.info(
        "[SCAN DEBUG] uploaded_file=%s filename=%s content_type=%s",
        bool(uploaded_file),
        getattr(uploaded_file, "filename", None),
        getattr(uploaded_file, "content_type", None),
    )

    # =====================================================
    # 1. KIỂM TRA ĐĂNG NHẬP
    # =====================================================

    if "user_id" not in session:

        return redirect(
            url_for("auth.login")
        )

    raw_scan_id = (
        request.form
        .get("scan_request_id", "")
        .strip()
        .lower()
    )

    if (
        len(raw_scan_id) == 32
        and all(
            character in "0123456789abcdef"
            for character in raw_scan_id
        )
    ):
        scan_id = raw_scan_id
    else:
        scan_id = uuid.uuid4().hex

    # =====================================================
    # KIỂM TRA SCAN BỊ GỬI LẠI
    # =====================================================

    if raw_scan_id == scan_id:

        try:

            existing_history = (
                ScanHistory.query
                .filter_by(
                    user_id=session["user_id"],
                    scan_id=scan_id,
                )
                .first()
            )

            if existing_history:

                return redirect(
                    url_for(
                        "history.scan_history_detail",
                        history_id=existing_history.id,
                    )
                )

        except SQLAlchemyError:

            db.session.rollback()

            logger.exception(
                "Could not check duplicate scan history."
            )

    # =====================================================
    # 2. KIỂM TRA FILE
    # =====================================================

    if uploaded_file is None:

        flash(
            "Vui lòng chọn ảnh.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    if uploaded_file.filename == "":

        flash(
            "Vui lòng chọn ảnh.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    # =====================================================
    # 3. KIỂM TRA ĐỊNH DẠNG
    # =====================================================

    extension = os.path.splitext(
        uploaded_file.filename
    )[1].lower()

    allowed_extensions = current_app.config[
        "ALLOWED_EXTENSIONS"
    ]

    if extension.replace(".", "") not in allowed_extensions:

        flash(
            "Định dạng ảnh không được hỗ trợ.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    expected_mime_types = {

        ".jpg": {
            "image/jpeg",
            "image/jpg",
        },

        ".jpeg": {
            "image/jpeg",
            "image/jpg",
        },

        ".png": {
            "image/png",
        },

        ".webp": {
            "image/webp",
        },
    }

    uploaded_mime_type = (
        uploaded_file.mimetype or ""
    ).lower()

    generic_mime_types = {
        "",
        "application/octet-stream",
        "binary/octet-stream",
    }

    if (
        uploaded_mime_type not in generic_mime_types
        and uploaded_mime_type
        not in expected_mime_types.get(
            extension,
            set(),
        )
    ):

        flash(
            "Định dạng nội dung ảnh không khớp "
            "với phần mở rộng tệp.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    current_app.logger.info(
        "[SCAN STAGE 3] file validation passed "
        "extension=%s content_type=%s",
        extension,
        uploaded_mime_type or "unspecified",
    )

    # =====================================================
    # 4. TẠO THƯ MỤC UPLOAD
    # =====================================================

    upload_folder = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
    )

    os.makedirs(
        upload_folder,
        exist_ok=True,
    )

    # =====================================================
    # 5. LƯU ẢNH
    # =====================================================

    filename = (
        str(uuid.uuid4())
        + extension
    )

    filepath = os.path.join(
        upload_folder,
        filename,
    )

    uploaded_file.save(filepath)

    current_app.logger.info(
        "[SCAN STAGE 5] file saved path=%s",
        filepath,
    )

    # =====================================================
    # 6. GEMINI
    # =====================================================

    try:

        current_app.logger.info(
            "[SCAN STAGE 6] calling analyze_product_image"
        )

        logger.info(
            "[SCAN RUNTIME] analyze_product_image module=%s",
            getattr(
                analyze_product_image,
                "__module__",
                None,
            ),
        )

        logger.info(
            "[SCAN RUNTIME] analyze_product_image file=%s",
            getattr(
                getattr(
                    analyze_product_image,
                    "__code__",
                    None,
                ),
                "co_filename",
                None,
            ),
        )

        try:

            source_file = inspect.getsourcefile(
                analyze_product_image
            )

        except (TypeError, OSError):

            source_file = None

        logger.info(
            "[SCAN RUNTIME] inspect source=%s",
            source_file,
        )

        label_data = analyze_product_image(
            filepath
        )

        current_app.logger.info(
            "[SCAN STAGE 7] analyze_product_image returned"
        )

    except GeminiConfigurationError:

        current_app.logger.error(
            "GEMINI_API_KEY is not configured."
        )

        flash(
            "Chức năng phân tích nhãn chưa được cấu hình. "
            "Vui lòng liên hệ quản trị viên.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    except InvalidProductImageError:

        flash(
            "Tệp tải lên không phải ảnh hợp lệ "
            "hoặc định dạng ảnh chưa được hỗ trợ.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    except GeminiServiceError as error:

        logger.error(
            "Gemini label analysis failed (%s).",
            type(error).__name__,
        )

        flash(
            "Gemini gặp lỗi khi phân tích ảnh: "
            f"{error}",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    # =====================================================
    # 7. NHẬN KẾT QUẢ GEMINI
    # =====================================================

    current_app.logger.info(
        "[SCAN STAGE 8] Gemini label data received"
    )

    product_name_from_gemini = (
        label_data.get("product_name", "")
    )

    brand_from_gemini = (
        label_data.get("brand", "")
    )

    gemini_ingredients = (
        label_data.get("ingredients", [])
    )

    gemini_allergens = (
        label_data.get("allergens", [])
    )

    # QUAN TRỌNG:
    # Đây là dị nguyên chỉ xuất hiện trong câu:
    #
    # May contain...
    # Kann ... enthalten
    # Có thể chứa...
    #
    # KHÔNG được đưa vào ingredients.

    gemini_may_contain_allergens = (
        label_data.get(
            "may_contain_allergens",
            [],
        )
    )

    # =====================================================
    # TEXT HIỂN THỊ
    # =====================================================

    text_parts = []

    if product_name_from_gemini:

        text_parts.append(
            "Tên sản phẩm: "
            + product_name_from_gemini
        )

    if gemini_ingredients:

        text_parts.append(
            "Thành phần: "
            + ", ".join(gemini_ingredients)
        )

    if gemini_allergens:

        text_parts.append(
            "Dị nguyên có trong thành phần: "
            + ", ".join(gemini_allergens)
        )

    if gemini_may_contain_allergens:

        text_parts.append(
            "Có thể chứa vết: "
            + ", ".join(
                gemini_may_contain_allergens
            )
        )

    text = (
        "\n".join(text_parts)
        or "Không đọc được nội dung từ ảnh."
    )

    # =====================================================
    # 8. TÌM SẢN PHẨM TRONG DATABASE
    # =====================================================

    try:

        current_app.logger.info(
            "[SCAN STAGE 9] product lookup started"
        )

        if (
            product_name_from_gemini
            and brand_from_gemini
        ):

            product = find_product_by_identity(
                product_name_from_gemini,
                brand_from_gemini,
            )

        else:

            product = None

    except SQLAlchemyError as error:

        logger.error(
            "Product identity lookup failed; "
            "continuing with Gemini data (%s).",
            type(error).__name__,
        )

        product = None

    current_app.logger.info(
        "[SCAN STAGE 10] product lookup finished"
    )

    # =====================================================
    # 9. LẤY THÀNH PHẦN
    # =====================================================

    current_app.logger.info(
        "[SCAN] catalog ingredient lookup started"
    )

    catalog_ingredients = (
        get_product_ingredients(product)
    )

    current_app.logger.info(
        "[SCAN] catalog ingredient lookup finished count=%s",
        len(catalog_ingredients),
    )

    # =====================================================
    # QUAN TRỌNG:
    # NORMALIZE + DEDUP MỘT LẦN
    #
    # Gemini + DB
    #        ↓
    # normalize
    #        ↓
    # product_ingredients
    #
    # Tất cả bước phía sau chỉ dùng biến này.
    # =====================================================

    product_ingredients = (
        normalize_and_deduplicate_ingredients(
            gemini_ingredients
            + catalog_ingredients
        )
    )

    current_app.logger.info(
        "[SCAN] normalized ingredient count=%s",
        len(product_ingredients),
    )

    # =====================================================
    # 10. LẤY DỊ NGUYÊN DATABASE
    # =====================================================

    current_app.logger.info(
        "[SCAN] catalog allergen lookup started"
    )

    product_allergens = (
        get_product_allergens(product)
    )

    current_app.logger.info(
        "[SCAN] catalog allergen lookup finished count=%s",
        len(product_allergens),
    )

    # =====================================================
    # 11. LẤY HỒ SƠ DỊ ỨNG USER
    # =====================================================

    current_app.logger.info(
        "[SCAN STAGE 11] allergy matching started"
    )

    try:

        user_allergens = (
            UserAllergen.query
            .filter_by(
                user_id=session["user_id"]
            )
            .all()
        )

    except SQLAlchemyError as error:

        logger.error(
            "Allergy profile lookup failed (%s).",
            type(error).__name__,
        )

        user_allergens = []

    user_allergen_tags = {

        item.allergen.off_tag

        for item in user_allergens

        if item.allergen
        and item.allergen.off_tag
    }

    # =====================================================
    # 12. SO SÁNH DỊ NGUYÊN
    # =====================================================

    # KHÔNG ĐƯỢC:
    #
    # product_ingredients + gemini_allergens
    #
    # Vì như vậy sẽ biến:
    #
    # LUPINEN
    #
    # trong câu:
    #
    # Kann ... LUPINEN enthalten
    #
    # thành thành phần thật.
    #
    # -----------------------------------------------------
    #
    # ĐÚNG:
    #
    # product_ingredients
    # product_allergens + gemini_allergens
    # gemini_may_contain_allergens
    # =====================================================

    allergens = check_product_ingredients(

        product_ingredients,

        user_allergen_tags,

        product_allergens
        + gemini_allergens,

        gemini_may_contain_allergens,
    )

    # =====================================================
    # 13. UNKNOWN
    # =====================================================

    match_unknown = should_mark_allergen_result_unknown(
        user_allergen_tags=user_allergen_tags,
        product_ingredients=product_ingredients,
        product_allergen_tags=product_allergens,
        gemini_allergens=gemini_allergens,
        may_contain_allergens=gemini_may_contain_allergens,
        matches=allergens,
    )

    current_app.logger.info(
        "[SCAN STAGE 12] allergy matching finished"
    )

    # =====================================================
    # 14. WARNING STATUS
    # =====================================================

    warning_status = (
        "unknown"
        if match_unknown
        else "warning"
        if allergens
        else "clear"
    )

    image_url = url_for(
        "static",
        filename=f"uploads/{filename}",
    )

    # =====================================================
    # 15. LƯU HISTORY
    # =====================================================

    history_record = None

    try:

        history_record, _created = (
            save_scan_history(

                scan_id=scan_id,

                user_id=session["user_id"],

                product_id=(
                    product.id
                    if product
                    else None
                ),

                product_name=(
                    product.name
                    if product
                    else product_name_from_gemini
                )
                or "Sản phẩm chưa xác định",

                brand=(
                    product.brand
                    if product
                    else brand_from_gemini
                ),

                image_url=image_url,

                ingredients=product_ingredients,

                allergens=list(
                    dict.fromkeys(
                        gemini_allergens
                        + product_allergens
                    )
                ),

                warnings=allergens,

                warning_status=warning_status,
            )
        )

    except SQLAlchemyError:

        logger.exception(
            "Could not save scan history; "
            "rendering analysis result anyway."
        )

    # =====================================================
    # 16. SAVE TOKEN
    # =====================================================

    save_token = None

    if (
        not product
        and product_name_from_gemini
    ):

        save_token = (
            URLSafeTimedSerializer(
                current_app.secret_key,
                salt=SCAN_SAVE_SALT,
            ).dumps(
                {
                    "scan_id": scan_id,

                    "product_name":
                        product_name_from_gemini,

                    "brand":
                        brand_from_gemini,

                    "ingredients":
                        gemini_ingredients,

                    "allergens":
                        gemini_allergens,

                    "may_contain_allergens":
                        gemini_may_contain_allergens,

                    "image_filename":
                        filename,
                }
            )
        )

    # =====================================================
    # 17. HIỂN THỊ KẾT QUẢ
    # =====================================================

    current_app.logger.info(
        "[SCAN STAGE 13] rendering scan_result.html"
    )

    return render_template(

        "scan_result.html",

        text=text,

        product=product,

        product_name=(
            product.name
            if product
            else product_name_from_gemini
        ),

        product_brand=(
            product.brand
            if product
            else brand_from_gemini
        ),

        save_token=save_token,

        gemini_allergens=
            gemini_allergens,

        gemini_may_contain_allergens=
            gemini_may_contain_allergens,

        match_unknown=
            match_unknown,

        product_ingredients=
            product_ingredients,

        product_allergens=
            product_allergens,

        allergens=
            allergens,

        image_path=url_for(
            "static",
            filename=f"uploads/{filename}",
        ),

        history_id=(
            history_record.id
            if history_record
            else None
        ),

        warning_status=
            warning_status,
    )


# =========================================================
# LƯU SẢN PHẨM
# =========================================================

@scan_bp.route(
    "/save-product",
    methods=["POST"],
)
def save_scan_product():

    if "user_id" not in session:

        return redirect(
            url_for("auth.login")
        )

    token = request.form.get(
        "save_token",
        "",
    )

    serializer = URLSafeTimedSerializer(
        current_app.secret_key,
        salt=SCAN_SAVE_SALT,
    )

    try:

        payload = serializer.loads(
            token,
            max_age=3600,
        )

    except (
        BadSignature,
        SignatureExpired,
    ):

        flash(
            "Kết quả quét đã hết hạn "
            "hoặc không hợp lệ. "
            "Vui lòng quét lại.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    token_key = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            token,
        )
    )

    saved_tokens = session.get(
        "saved_scan_tokens",
        [],
    )

    if token_key in saved_tokens:

        flash(
            "Sản phẩm đã được lưu trước đó.",
            "info",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    # =====================================================
    # KIỂM TRA PAYLOAD
    # =====================================================

    image_filename = payload.get(
        "image_filename",
        "",
    )

    if (
        not isinstance(
            image_filename,
            str,
        )

        or os.path.basename(
            image_filename
        ) != image_filename

        or os.path.splitext(
            image_filename
        )[1].lower()
        not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }
    ):

        flash(
            "Không thể xác định ảnh "
            "của kết quả quét. "
            "Vui lòng quét lại.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    image_path = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        image_filename,
    )

    if not os.path.isfile(image_path):

        flash(
            "Ảnh kết quả quét không còn tồn tại. "
            "Vui lòng quét lại.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    # =====================================================
    # LƯU PRODUCT
    # =====================================================

    try:

        product, created = save_scanned_product(

            payload,

            url_for(
                "static",
                filename=(
                    f"uploads/{image_filename}"
                ),
            ),
        )

    except Exception:

        logger.exception(
            "Saving scanned product failed."
        )

        flash(
            "Không thể lưu sản phẩm lúc này. "
            "Vui lòng thử lại sau.",
            "error",
        )

        return redirect(
            url_for("scan.scan_page")
        )

    # =====================================================
    # LINK HISTORY
    # =====================================================

    scan_id = payload.get(
        "scan_id"
    )

    if (
        isinstance(scan_id, str)
        and len(scan_id) == 32
    ):

        try:

            attach_product_to_scan_history(

                user_id=
                    session["user_id"],

                scan_id=
                    scan_id,

                product_id=
                    product.id,
            )

        except SQLAlchemyError:

            logger.exception(
                "Product saved but scan history "
                "could not be linked."
            )

    # =====================================================
    # ĐÁNH DẤU TOKEN ĐÃ LƯU
    # =====================================================

    saved_tokens.append(
        token_key
    )

    session[
        "saved_scan_tokens"
    ] = saved_tokens[-20:]

    if created:

        flash(
            "Đã lưu sản phẩm vào cơ sở dữ liệu.",
            "success",
        )

    else:

        flash(
            "Sản phẩm đã tồn tại "
            "trong cơ sở dữ liệu.",
            "info",
        )

    return redirect(
        url_for("scan.scan_page")
    )