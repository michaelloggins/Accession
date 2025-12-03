"""Seed script to create a test user for development."""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.user import User
from app.config import settings

def seed_user():
    """Create a test admin user."""
    # Create database connection
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == "admin@miravista.com").first()

        if existing_user:
            print("NOTICE: User already exists: admin@miravista.com")
            print(f"  Name: {existing_user.full_name}")
            print(f"  Role: {existing_user.role}")
            print(f"  Active: {existing_user.is_active}")
            return

        # Create admin user
        admin_user = User(
            id="dev-admin-001",  # Development user ID
            email="admin@miravista.com",
            full_name="MiraVista Admin",
            role="admin",
            is_active=True,
            mfa_enabled=False,
            failed_login_attempts=0,
            created_at=datetime.now(),
            created_by="system"
        )

        db.add(admin_user)

        # Create reviewer user
        reviewer_user = User(
            id="dev-reviewer-001",
            email="reviewer@miravista.com",
            full_name="Lab Reviewer",
            role="reviewer",
            is_active=True,
            mfa_enabled=False,
            failed_login_attempts=0,
            created_at=datetime.now(),
            created_by="system"
        )

        db.add(reviewer_user)

        # Create read-only auditor
        auditor_user = User(
            id="dev-auditor-001",
            email="auditor@miravista.com",
            full_name="Compliance Auditor",
            role="read_only",
            is_active=True,
            mfa_enabled=False,
            failed_login_attempts=0,
            created_at=datetime.now(),
            created_by="system"
        )

        db.add(auditor_user)

        db.commit()

        print("SUCCESS: Test users created!")
        print("\nUser Accounts Created:")
        print("-" * 60)
        print("1. Admin User:")
        print("   Email: admin@miravista.com")
        print("   Role: admin")
        print("   ID: dev-admin-001")
        print()
        print("2. Reviewer User:")
        print("   Email: reviewer@miravista.com")
        print("   Role: reviewer")
        print("   ID: dev-reviewer-001")
        print()
        print("3. Auditor User:")
        print("   Email: auditor@miravista.com")
        print("   Role: read_only")
        print("   ID: dev-auditor-001")
        print("-" * 60)
        print("\nNote: In production, users are authenticated via Azure AD.")
        print("For development, these test accounts bypass Azure AD authentication.")

    except Exception as e:
        print(f"ERROR: Failed to create users: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_user()
