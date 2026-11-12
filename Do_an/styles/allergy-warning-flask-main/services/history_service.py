import json

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from extensions import db
from models import ScanHistory


def save_scan_history(
    *,
    scan_id,
    user_id,
    product_id,
    product_name,
    brand,
    image_url,
    ingredients,
    allergens,
    warnings,
    warning_status,
):
    """Save one immutable scan snapshot, returning an existing duplicate token."""
    try:
        existing = ScanHistory.query.filter_by(
            user_id=user_id,
            scan_id=scan_id,
        ).first()
        if existing:
            if existing.product_id is None and product_id is not None:
                existing.product_id = product_id
                db.session.commit()
            return existing, False

        history = ScanHistory(
            scan_id=scan_id,
            user_id=user_id,
            product_id=product_id,
            product_name=product_name,
            brand=brand or None,
            image_url=image_url or None,
            ingredients_json=json.dumps(ingredients or [], ensure_ascii=False),
            allergens_json=json.dumps(allergens or [], ensure_ascii=False),
            warnings_json=json.dumps(warnings or [], ensure_ascii=False),
            warning_status=warning_status,
        )
        db.session.add(history)
        db.session.commit()
        return history, True
    except IntegrityError:
        db.session.rollback()
        existing = ScanHistory.query.filter_by(
            user_id=user_id,
            scan_id=scan_id,
        ).first()
        if existing:
            return existing, False
        raise
    except SQLAlchemyError:
        db.session.rollback()
        raise


def attach_product_to_scan_history(*, user_id, scan_id, product_id):
    """Link a user's scan snapshot to a product approved and saved later."""
    try:
        history = ScanHistory.query.filter_by(
            user_id=user_id,
            scan_id=scan_id,
        ).first()
        if not history:
            return False
        if history.product_id != product_id:
            history.product_id = product_id
            db.session.commit()
        return True
    except SQLAlchemyError:
        db.session.rollback()
        raise
