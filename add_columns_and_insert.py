"""Add break glass columns and insert admin into Azure SQL."""
import struct
from azure.identity import AzureCliCredential
import pyodbc

SERVER = "mvd-docintel-sql.database.windows.net"
DATABASE = "accession-dev-db"

# BCrypt hash of password "Mv9Br3akGlass2024xAdm1n!"
PASSWORD_HASH = "$2b$12$d92fjymi.pekhKwX4zdw8.5W7OsX/OgBx4OIBQkNzsUJdgxv9lKqC"

def get_token():
    """Get Azure AD token for SQL."""
    credential = AzureCliCredential()
    token = credential.get_token("https://database.windows.net/.default")
    return token.token

def get_connection():
    """Create pyodbc connection with Azure AD token."""
    token = get_token()
    token_bytes = token.encode("UTF-16-LE")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)

    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server={SERVER};"
        f"Database={DATABASE};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
    )

    conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})
    return conn

def add_columns_and_insert():
    """Add break glass columns if not exist, then insert admin."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check and add hashed_password column
    cursor.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('users') AND name = 'hashed_password'
        )
        ALTER TABLE users ADD hashed_password NVARCHAR(255) NULL
    """)
    conn.commit()
    print("Added hashed_password column (if not exists)")

    # Check and add is_break_glass column
    cursor.execute("""
        IF NOT EXISTS (
            SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('users') AND name = 'is_break_glass'
        )
        ALTER TABLE users ADD is_break_glass BIT NOT NULL DEFAULT 0
    """)
    conn.commit()
    print("Added is_break_glass column (if not exists)")

    # Check if user exists
    cursor.execute("SELECT id FROM users WHERE email = ?", ('breakglass.admin@miravista.com',))
    row = cursor.fetchone()

    if row:
        # Update existing
        cursor.execute("""
            UPDATE users
            SET hashed_password = ?,
                is_break_glass = 1,
                is_active = 1,
                role = 'admin',
                updated_at = GETUTCDATE()
            WHERE email = ?
        """, (PASSWORD_HASH, 'breakglass.admin@miravista.com'))
        print("Break glass admin updated")
    else:
        # Insert new
        cursor.execute("""
            INSERT INTO users (
                id, email, full_name, first_name, last_name,
                role, is_active, auth_provider, mfa_enabled,
                failed_login_attempts, hashed_password, is_break_glass,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETUTCDATE(), ?)
        """, (
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
            PASSWORD_HASH,
            1,
            'system'
        ))
        print("Break glass admin created")

    conn.commit()

    # Verify
    cursor.execute("""
        SELECT id, email, full_name, role, is_active, is_break_glass,
               CASE WHEN hashed_password IS NOT NULL THEN 'SET' ELSE 'NOT SET' END as pwd_status
        FROM users
        WHERE email = 'breakglass.admin@miravista.com'
    """)
    row = cursor.fetchone()
    if row:
        print(f"Verified: id={row.id}, email={row.email}, role={row.role}, active={row.is_active}, break_glass={row.is_break_glass}, pwd={row.pwd_status}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    add_columns_and_insert()
