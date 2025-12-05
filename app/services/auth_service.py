"""Authentication service for user management."""

from datetime import datetime, timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt
import logging

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

# Password hashing context for break glass accounts
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Service for authentication and authorization."""

    def __init__(self, db: Session):
        self.db = db

    def authenticate(self, email: str, password: str):
        """Authenticate user with email and password. MFA is handled by Azure AD SSO."""
        user = self.db.query(User).filter(User.email == email).first()

        if not user:
            logger.warning(f"Login attempt for non-existent user: {email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Check if account is locked
        if user.account_locked_until and user.account_locked_until > datetime.utcnow():
            logger.warning(f"Login attempt for locked account: {email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is temporarily locked"
            )

        # Check if user is active
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated"
            )

        # Verify password (integrate with Azure AD in production)
        if not self._verify_password(password, user):
            self._handle_failed_login(user)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Note: MFA is handled at the Azure AD SSO level, not in this application.
        # If user.mfa_enabled is True but they're using local auth, warn and proceed.
        if user.mfa_enabled:
            logger.warning(f"User {email} has mfa_enabled=True but is using local auth. MFA should be enforced via Azure AD SSO.")

        # Reset failed login attempts
        user.failed_login_attempts = 0
        user.last_login = datetime.utcnow()
        self.db.commit()

        # Generate JWT token
        token, expires_in = self._generate_token(user)

        return user, token, expires_in

    def _verify_password(self, password: str, user: User) -> bool:
        """Verify user password for break glass accounts.
        
        For break glass accounts, verify against bcrypt-hashed password.
        For SSO accounts, this should not be called (auth via Entra ID).
        """
        # Only break glass accounts can use local password auth
        if not user.is_break_glass:
            logger.warning(f"Non-break-glass account {user.email} attempted local password auth")
            return False
        
        # Verify password exists
        if not user.hashed_password:
            logger.warning(f"Break glass account {user.email} has no password set")
            return False
        
        # Verify bcrypt password
        return pwd_context.verify(password, user.hashed_password)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt for break glass accounts."""
        return pwd_context.hash(password)

    def _handle_failed_login(self, user: User):
        """Handle failed login attempt."""
        user.failed_login_attempts += 1

        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.account_locked_until = datetime.utcnow() + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
            logger.warning(f"Account locked due to failed attempts: {user.email}")

        self.db.commit()

    def generate_token(self, user: User):
        """Generate JWT token for authenticated user."""
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        expire = datetime.utcnow() + timedelta(seconds=expires_in)

        payload = {
            "sub": user.id,
            "email": user.email,
            "role": user.role,
            "exp": expire
        }

        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return token, expires_in

    # Alias for backwards compatibility
    _generate_token = generate_token

    def verify_token(self, token: str) -> dict:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

    def get_user_by_id(self, user_id: str) -> User:
        """Get user by ID."""
        return self.db.query(User).filter(User.id == user_id).first()

    def check_permission(self, user: User, permission: str) -> bool:
        """Check if user has specific permission."""
        from app.config import ROLES
        user_permissions = ROLES.get(user.role, {}).get("permissions", [])
        return permission in user_permissions


def get_current_user_from_request(request, db: Session) -> dict:
    """
    Extract current user info from request (JWT token in header or cookie).

    Returns dict with user_id and user_email, or defaults for system/anonymous.
    """
    from app.config import settings

    # Get token from header or cookie
    auth_header = request.headers.get("Authorization")
    access_token_cookie = request.cookies.get("access_token")

    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
    elif access_token_cookie:
        token = access_token_cookie

    if not token:
        return {"user_id": "anonymous", "user_email": "anonymous"}

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return {
            "user_id": payload.get("sub", "unknown"),
            "user_email": payload.get("email", "unknown@system")
        }
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return {"user_id": "invalid-token", "user_email": "invalid@token"}


def require_admin(request, db: Session):
    """
    Dependency that requires the current user to have admin role.
    Raises 403 if not admin.
    """
    # Get token from header or cookie
    auth_header = request.headers.get("Authorization")
    access_token_cookie = request.cookies.get("access_token")

    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
    elif access_token_cookie:
        token = access_token_cookie

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_role = payload.get("role", "read_only")

        if user_role != "admin":
            logger.warning(f"Non-admin user {payload.get('email')} attempted to access admin endpoint")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )

        return {
            "user_id": payload.get("sub"),
            "user_email": payload.get("email"),
            "role": user_role
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
