"""Create a test user for local development."""

from app.database import SessionLocal, engine, Base
from app.models.user import User
from datetime import datetime

# Create tables
Base.metadata.create_all(bind=engine)

# Create session
db = SessionLocal()

# Create test user
test_user = User(
    id="test-user-001",
    email="admin@test.com",
    full_name="Test Admin",
    role="admin",
    is_active=True,
    mfa_enabled=False,
    created_at=datetime.utcnow()
)

# Check if user exists
existing = db.query(User).filter(User.email == "admin@test.com").first()
if not existing:
    db.add(test_user)
    db.commit()
    print("✓ Test user created!")
    print("  Email: admin@test.com")
    print("  Password: any password (auth is mocked for dev)")
else:
    print("✓ Test user already exists")
    print("  Email: admin@test.com")

db.close()
