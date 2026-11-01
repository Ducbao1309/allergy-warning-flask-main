
from app import app
from extensions import db
from sqlalchemy import text

try:
    with app.app_context():
        result = db.session.execute(
            text("SELECT DATABASE(), VERSION()")
        ).fetchone()

        print("KET NOI DATABASE THANH CONG!")
        print("Database:", result[0])
        print("Version:", result[1])

        tables = db.session.execute(
            text("SHOW TABLES")
        ).fetchall()

        print("\nDANH SACH BANG:")
        for table in tables:
            print("-", table[0])

except Exception as e:
    print("KET NOI THAT BAI!")
    print("Loi:", e)
