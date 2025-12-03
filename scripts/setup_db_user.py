"""
Script to create Azure AD user in the database.
"""
import pyodbc
import struct
from azure.identity import AzureCliCredential

SERVER = 'mvd-docintel-sql.database.windows.net'
DATABASE = 'docintel-db'
DRIVER = '{ODBC Driver 18 for SQL Server}'

def get_connection(database='master'):
    """Get Azure SQL connection using Azure CLI credential."""
    credential = AzureCliCredential()
    token = credential.get_token("https://database.windows.net/.default")

    token_bytes = token.token.encode("UTF-16-LE")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
    SQL_COPT_SS_ACCESS_TOKEN = 1256

    conn_str = (
        f'DRIVER={DRIVER};'
        f'SERVER={SERVER};'
        f'DATABASE={database};'
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})

def main():
    print("Setting up database user...")
    user_email = "mloggins@miravistalabs.com"

    try:
        # Connect to the target database and create user
        print(f"Connecting to {DATABASE} to create contained user...")
        conn = get_connection(DATABASE)
        cursor = conn.cursor()

        # Create contained database user
        print(f"Creating user for {user_email}...")
        try:
            cursor.execute(f"""
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = '{user_email}')
                BEGIN
                    CREATE USER [{user_email}] FROM EXTERNAL PROVIDER;
                END
            """)
            conn.commit()
            print("User created or already exists.")
        except Exception as e:
            print(f"Note: {e}")

        # Grant permissions
        print("Granting db_owner permissions...")
        try:
            cursor.execute(f"ALTER ROLE db_owner ADD MEMBER [{user_email}]")
            conn.commit()
            print("Permissions granted.")
        except Exception as e:
            print(f"Note: {e}")

        cursor.close()
        conn.close()
        print("\nDatabase user setup complete!")

    except Exception as e:
        print(f"Error: {e}")

        # If we can't connect to the DB directly, try via master
        print("\nTrying to create user via master database...")
        try:
            conn = get_connection('master')
            cursor = conn.cursor()

            # First check what databases exist
            cursor.execute("SELECT name FROM sys.databases WHERE name NOT IN ('master', 'tempdb', 'model', 'msdb')")
            dbs = cursor.fetchall()
            print(f"Found databases: {[d[0] for d in dbs]}")

            # Create the contained user via USE statement
            cursor.execute(f"""
                USE [{DATABASE}];
                IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = '{user_email}')
                BEGIN
                    CREATE USER [{user_email}] FROM EXTERNAL PROVIDER;
                END;
                ALTER ROLE db_owner ADD MEMBER [{user_email}];
            """)
            conn.commit()
            print("User created via master!")

            cursor.close()
            conn.close()
        except Exception as e2:
            print(f"Master approach also failed: {e2}")
            raise

if __name__ == "__main__":
    main()
