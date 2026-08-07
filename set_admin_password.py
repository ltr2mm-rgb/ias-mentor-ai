"""
One-off helper to set (or reset) the password for an admin account so you can
log into the /admin dashboard. Uses the same bcrypt hashing the app uses.

Usage (from the project folder):
    py -3 set_admin_password.py ltr2mm@gmail.com YourNewPassword123

If the account doesn't exist yet it will be created. Built-in admin emails
(see config.ADMIN_EMAILS) automatically get admin access on login.
"""
import sys
import sqlite3
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
DB = "ias_mentor.db"


def main():
    if len(sys.argv) != 3:
        print("Usage: py -3 set_admin_password.py <email> <new_password>")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    new_password = sys.argv[2]
    hashed = pwd.hash(new_password)

    db = sqlite3.connect(DB)
    c = db.cursor()
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    row = c.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()

    if row:
        c.execute("UPDATE users SET hashed_password=? WHERE id=?", (hashed, row[0]))
        print(f"Updated password for existing account: {email}")
    else:
        fields = ["name", "email", "hashed_password"]
        values = ["Admin", email, hashed]
        if "created_at" in cols:
            fields.append("created_at")
            values.append(__import__("datetime").datetime.utcnow().isoformat())
        placeholders = ",".join("?" * len(values))
        c.execute(f"INSERT INTO users ({','.join(fields)}) VALUES ({placeholders})", values)
        print(f"Created new account: {email}")

    db.commit()
    db.close()
    print("Done. You can now log in at http://localhost:8000/admin")


if __name__ == "__main__":
    main()
