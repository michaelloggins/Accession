"""Insert break glass admin directly into Azure SQL using Azure AD auth."""
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
    # Convert token to bytes for SQL Server
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

def insert_break_glass_admin():
    """Insert or update break glass admin."""
    conn = get_connection()
    cursor = conn.cursor()

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
        print(f"Verified: {row}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    insert_break_glass_admin()
