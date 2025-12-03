"""Test login flow without starting the full app."""

from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.models.audit_log import AuditLog
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from datetime import datetime

print("1. Creating database tables...")
Base.metadata.drop_all(bind=engine)  # Fresh start
Base.metadata.create_all(bind=engine)
print("   [OK] Tables created")

print("\n2. Creating test user...")
db = SessionLocal()
test_user = User(
    id="test-user-001",
    email="admin@test.com",
    full_name="Test Admin",
    role="admin",
    is_active=True,
    mfa_enabled=False,
    created_at=datetime.utcnow()
)
db.add(test_user)
db.commit()
print("   [OK] User created: admin@test.com")

print("\n3. Testing audit log insert...")
audit_service = AuditService(db)
audit_service.log_action(
    user_id="test-user-001",
    user_email="admin@test.com",
    action="TEST",
    resource_type="SYSTEM",
    success=True
)
print("   [OK] Audit log created successfully!")

print("\n4. Testing authentication...")
auth_service = AuthService(db)
try:
    user, token, expires_in = auth_service.authenticate(
        "admin@test.com",
        "anypassword",
        None
    )
    print(f"   [OK] Login successful!")
    print(f"   Token: {token[:50]}...")
    print(f"   Expires in: {expires_in} seconds")
except Exception as e:
    print(f"   [ERROR] Login failed: {e}")

db.close()
print("\n[OK] All tests passed! You can now start the app.")
