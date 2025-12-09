-- Insert Break Glass Admin Account
-- This is a one-time setup for emergency access when SSO is unavailable

-- First check if user already exists
IF NOT EXISTS (SELECT 1 FROM users WHERE email = 'breakglass.admin@miravista.com')
BEGIN
    INSERT INTO users (
        id,
        email,
        full_name,
        first_name,
        last_name,
        role,
        is_active,
        auth_provider,
        mfa_enabled,
        failed_login_attempts,
        hashed_password,
        is_break_glass,
        created_at,
        created_by
    ) VALUES (
        'break-glass-admin-001',
        'breakglass.admin@miravista.com',
        'Break Glass Administrator',
        'Break Glass',
        'Administrator',
        'admin',
        1,
        'local',
        0,
        0,
        '$2b$12$d92fjymi.pekhKwX4zdw8.5W7OsX/OgBx4OIBQkNzsUJdgxv9lKqC',
        1,
        GETUTCDATE(),
        'system'
    );
    PRINT 'Break glass admin account created successfully';
END
ELSE
BEGIN
    -- Update existing account with new password hash
    UPDATE users
    SET hashed_password = '$2b$12$d92fjymi.pekhKwX4zdw8.5W7OsX/OgBx4OIBQkNzsUJdgxv9lKqC',
        is_break_glass = 1,
        is_active = 1,
        role = 'admin',
        updated_at = GETUTCDATE()
    WHERE email = 'breakglass.admin@miravista.com';
    PRINT 'Break glass admin account updated successfully';
END

-- Verify the insert/update
SELECT id, email, full_name, role, is_active, auth_provider, is_break_glass,
       CASE WHEN hashed_password IS NOT NULL THEN 'SET' ELSE 'NOT SET' END as password_status
FROM users
WHERE email = 'breakglass.admin@miravista.com';
