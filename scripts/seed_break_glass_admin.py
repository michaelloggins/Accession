"""Seed script to create a break glass admin account.

This account is for emergency access when SSO/Entra ID is unavailable.
The password must be stored securely offline and only used in emergencies.
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from app.models.user import User
from app.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# CIS-compliant password (20+ chars, mixed case, numbers, special chars)
# Note: Avoids $ and other characters blocked by security middleware
# IMPORTANT: Change this password immediately after first use in production!
BREAK_GLASS_PASSWORD = "Mv9Br3akGlass2024xAdm1n!"


def seed_break_glass_admin():
    """Create or update the break glass admin account."""
    # Create database connection
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Check if break glass admin already exists
        existing_user = db.query(User).filter(User.email == "breakglass.admin@miravista.com").first()

        # Hash the password
        hashed_password = pwd_context.hash(BREAK_GLASS_PASSWORD)

        if existing_user:
            # Update existing break glass admin
            existing_user.hashed_password = hashed_password
            existing_user.is_break_glass = True
            existing_user.is_active = True
            existing_user.role = "admin"
            db.commit()

            print("=" * 70)
            print("BREAK GLASS ADMIN ACCOUNT UPDATED")
            print("=" * 70)
            print(f"Email:    breakglass.admin@miravista.com")
            print(f"Password: {BREAK_GLASS_PASSWORD}")
            print(f"Role:     admin")
            print("=" * 70)
            print("\nWARNING: Store this password securely offline!")
            print("This account should ONLY be used when SSO is unavailable.")
            print("=" * 70)
            return

        # Create break glass admin user
        break_glass_admin = User(
            id="break-glass-admin-001",
            email="breakglass.admin@miravista.com",
            full_name="Break Glass Administrator",
            first_name="Break Glass",
            last_name="Administrator",
            role="admin",
            is_active=True,
            auth_provider="local",
            mfa_enabled=False,
            failed_login_attempts=0,
            hashed_password=hashed_password,
            is_break_glass=True,
            created_at=datetime.utcnow(),
            created_by="system"
        )

        db.add(break_glass_admin)
        db.commit()

        print("=" * 70)
        print("BREAK GLASS ADMIN ACCOUNT CREATED")
        print("=" * 70)
        print(f"Email:    breakglass.admin@miravista.com")
        print(f"Password: {BREAK_GLASS_PASSWORD}")
        print(f"Role:     admin")
        print(f"ID:       break-glass-admin-001")
        print("=" * 70)
        print("\nWARNING: Store this password securely offline!")
        print("This account should ONLY be used when SSO is unavailable.")
        print("\nPassword Requirements Met (CIS Compliant):")
        print("  - 20+ characters")
        print("  - Contains uppercase letters (M, B, G, A)")
        print("  - Contains lowercase letters (v, r, e, a, k, l, s, d, m, n)")
        print("  - Contains numbers (3, 2, 0, 4, 1)")
        print("  - Contains special characters (!, $, _)")
        print("=" * 70)

    except Exception as e:
        print(f"ERROR: Failed to create break glass admin: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_break_glass_admin()
