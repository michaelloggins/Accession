"""
Bulk import facilities data from RASCLIENTS.csv into Azure SQL Server using BULK INSERT.

This approach:
1. Uploads the CSV to Azure Blob Storage
2. Creates database credentials and external data source (if not exists)
3. Uses BULK INSERT for maximum performance

BULK INSERT is significantly faster than row-by-row inserts for large datasets.
"""
import pyodbc
import struct
import time
import subprocess
from datetime import datetime, timedelta
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

# Azure SQL connection settings
SQL_SERVER = 'mvd-docintel-sql.database.windows.net'
SQL_DATABASE = 'docintel-db'
DRIVER = '{ODBC Driver 18 for SQL Server}'

# Azure Storage settings
STORAGE_ACCOUNT = 'mvddocintelstore'
CONTAINER_NAME = 'documents'
BLOB_NAME = 'imports/RASCLIENTS.csv'

# Local file
CSV_FILE = r'C:\Projects\DocIntelligence\RASCLIENTS.csv'

def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {message}", flush=True)

def get_sql_connection():
    """Get Azure SQL connection using Azure CLI credential."""
    credential = AzureCliCredential()
    token = credential.get_token("https://database.windows.net/.default")

    token_bytes = token.token.encode("UTF-16-LE")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
    SQL_COPT_SS_ACCESS_TOKEN = 1256

    conn_str = f'DRIVER={DRIVER};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};'
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})

def upload_csv_to_blob():
    """Upload CSV file to Azure Blob Storage and return SAS token."""
    log(f"Uploading {CSV_FILE} to blob storage...")

    # Use az CLI with account key auth (more reliable permissions)
    # Use shell=True on Windows to find az.cmd
    result = subprocess.run(
        f'az storage blob upload --account-name {STORAGE_ACCOUNT} --container-name {CONTAINER_NAME} '
        f'--name {BLOB_NAME} --file "{CSV_FILE}" --auth-mode key --overwrite',
        capture_output=True, text=True, shell=True
    )

    if result.returncode != 0:
        raise Exception(f"Failed to upload blob: {result.stderr}")

    log(f"Uploaded to: https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{BLOB_NAME}")

    # Get account key for SAS generation
    result = subprocess.run(
        f'az storage account keys list --account-name {STORAGE_ACCOUNT} --query "[0].value" -o tsv',
        capture_output=True, text=True, shell=True
    )
    account_key = result.stdout.strip()

    # Generate SAS token valid for 1 hour
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT,
        container_name=CONTAINER_NAME,
        blob_name=BLOB_NAME,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1)
    )

    log("Generated SAS token for blob access")

    return sas_token

def setup_database_objects(cursor, sas_token):
    """Create database credential and external data source for blob access."""
    log("Setting up database objects for blob access...")

    # Check if master key exists, create if not
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.symmetric_keys WHERE name = '##MS_DatabaseMasterKey##')
        BEGIN
            CREATE MASTER KEY ENCRYPTION BY PASSWORD = 'DocIntel2024!SecureKey#';
        END
    """)

    # Drop external data source first (it depends on the credential)
    cursor.execute("""
        IF EXISTS (SELECT * FROM sys.external_data_sources WHERE name = 'BlobStorage')
            DROP EXTERNAL DATA SOURCE BlobStorage;
    """)

    # Drop and recreate credential (SAS tokens expire)
    cursor.execute("""
        IF EXISTS (SELECT * FROM sys.database_scoped_credentials WHERE name = 'BlobStorageCredential')
            DROP DATABASE SCOPED CREDENTIAL BlobStorageCredential;
    """)

    # Create credential with SAS token (remove leading '?' if present)
    sas_secret = sas_token.lstrip('?')
    cursor.execute(f"""
        CREATE DATABASE SCOPED CREDENTIAL BlobStorageCredential
        WITH IDENTITY = 'SHARED ACCESS SIGNATURE',
        SECRET = '{sas_secret}';
    """)
    log("Created database scoped credential")

    # Create external data source
    cursor.execute(f"""
        CREATE EXTERNAL DATA SOURCE BlobStorage
        WITH (
            TYPE = BLOB_STORAGE,
            LOCATION = 'https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}',
            CREDENTIAL = BlobStorageCredential
        );
    """)
    log("Created external data source")

def create_facilities_table(cursor):
    """Drop and recreate the facilities table."""
    log("Creating facilities table...")

    # Drop foreign key constraints and table
    cursor.execute("""
        DECLARE @sql NVARCHAR(MAX) = N'';
        SELECT @sql += 'ALTER TABLE ' + QUOTENAME(OBJECT_SCHEMA_NAME(parent_object_id))
            + '.' + QUOTENAME(OBJECT_NAME(parent_object_id))
            + ' DROP CONSTRAINT ' + QUOTENAME(name) + ';'
        FROM sys.foreign_keys
        WHERE referenced_object_id = OBJECT_ID('dbo.facilities');
        EXEC sp_executesql @sql;
    """)

    cursor.execute("""
        IF OBJECT_ID('dbo.facilities', 'U') IS NOT NULL
            DROP TABLE dbo.facilities;
    """)

    # Create table - columns match CSV order exactly for BULK INSERT
    cursor.execute("""
        CREATE TABLE dbo.facilities (
            ORIGREC INT NULL,
            ADRESS NVARCHAR(500) NULL,
            ADRESS_A NVARCHAR(500) NULL,
            CATEGORY NVARCHAR(100) NULL,
            CITY NVARCHAR(100) NULL,
            COMPNAME NVARCHAR(500) NULL,
            COUNTRY NVARCHAR(100) NULL,
            COUNTY NVARCHAR(100) NULL,
            DEFAULTCONTACT NVARCHAR(255) NULL,
            EXTERNALCLIENTID NVARCHAR(50) NULL,
            HL7_ID NVARCHAR(50) NULL,
            ORIGSTS NVARCHAR(10) NULL,
            POB NVARCHAR(100) NULL,
            PRIMARYFAX NVARCHAR(100) NULL,
            PRIMARYPHONE NVARCHAR(100) NULL,
            RASCLIENTID NVARCHAR(50) NULL,
            STATE NVARCHAR(10) NULL,
            UDPARAM0 NVARCHAR(255) NULL,
            UDPARAM1 NVARCHAR(255) NULL,
            UDPARAM2 NVARCHAR(255) NULL,
            UDPARAM3 NVARCHAR(255) NULL,
            UDPARAM4 NVARCHAR(255) NULL,
            URL NVARCHAR(500) NULL,
            VMDPATH NVARCHAR(500) NULL,
            ZIP NVARCHAR(20) NULL,
            OWNER NVARCHAR(10) NULL,
            EMAIL NVARCHAR(255) NULL,
            ACCOUNT_NAME NVARCHAR(500) NULL,
            DELINQUENT NVARCHAR(10) NULL,
            ORGANIZATIONAL_OID NVARCHAR(100) NULL,
            APPLICATION_OID_PROD NVARCHAR(100) NULL,
            DEV_INBOUND_RESULTS NVARCHAR(255) NULL,
            DEV_OUTBOUND_ORDERS NVARCHAR(255) NULL,
            DEV_OUTBOUND_RESULTS NVARCHAR(255) NULL,
            DEV_INBOUND_ORDERS NVARCHAR(255) NULL,
            APPLICATION_OID_DEV NVARCHAR(100) NULL,
            PROD_INBOUND_ORDERS NVARCHAR(255) NULL,
            PROD_INBOUND_RESULTS NVARCHAR(255) NULL,
            PROD_OUTBOUND_ORDERS NVARCHAR(255) NULL,
            PROD_OUTBOUND_RESULTS NVARCHAR(255) NULL,
            HL7_CONTACT NVARCHAR(255) NULL,
            HL7_CONTACT_PHONE NVARCHAR(100) NULL,
            HL7_CONTACT_EMAIL NVARCHAR(255) NULL,
            DEV_APPLICATION_NAME NVARCHAR(255) NULL,
            PROD_APPLICATION_NAME NVARCHAR(255) NULL,
            STATUS NVARCHAR(50) NULL,
            START_DATE NVARCHAR(50) NULL,
            PRICELISTID NVARCHAR(100) NULL,
            JURISDICTION_TYPE NVARCHAR(100) NULL,
            JURISDICTION_CODE NVARCHAR(100) NULL,
            CLIENT_USAGE NVARCHAR(50) NULL,
            NETWORK_SHARED_PATH NVARCHAR(500) NULL,
            SECONDARYPHONE NVARCHAR(100) NULL,
            PHONEEXTENSION1 NVARCHAR(20) NULL,
            PHONEEXTENSION2 NVARCHAR(20) NULL,
            PAGERCELL NVARCHAR(50) NULL,
            FAXCOUNTRYCODE NVARCHAR(10) NULL,
            FAXAREACODE NVARCHAR(10) NULL,
            FAXLOCALNUMBER NVARCHAR(20) NULL,
            PHONECOUNTRYCODE NVARCHAR(10) NULL,
            PHONEAREACODE NVARCHAR(10) NULL,
            PHONELOCALNUMBER NVARCHAR(20) NULL,
            LABDIRECTORDEGREE NVARCHAR(50) NULL,
            IS_PRIMARY NVARCHAR(10) NULL,
            DEPARTMENT NVARCHAR(255) NULL,
            INTERFACE_ID NVARCHAR(100) NULL,
            PANEL_PRELIMINARY NVARCHAR(10) NULL
        );
    """)
    log("Facilities table created")

def run_bulk_insert(cursor):
    """Execute BULK INSERT from blob storage."""
    log("Starting BULK INSERT from blob storage...")

    start_time = time.time()

    cursor.execute(f"""
        BULK INSERT dbo.facilities
        FROM '{BLOB_NAME}'
        WITH (
            DATA_SOURCE = 'BlobStorage',
            FORMAT = 'CSV',
            FIRSTROW = 2,
            FIELDTERMINATOR = ',',
            ROWTERMINATOR = '0x0a',
            FIELDQUOTE = '"',
            TABLOCK,
            MAXERRORS = 0
        );
    """)

    elapsed = time.time() - start_time
    log(f"BULK INSERT completed in {elapsed:.2f}s")

    return elapsed

def cleanup_null_strings(cursor):
    """Convert 'NULL' strings to actual SQL NULLs."""
    log("Converting 'NULL' strings to actual NULLs...")

    # Get all NVARCHAR columns from the table
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'facilities'
          AND TABLE_SCHEMA = 'dbo'
          AND DATA_TYPE = 'nvarchar'
    """)
    columns = [row[0] for row in cursor.fetchall()]

    # Build UPDATE statement to convert 'NULL' strings to actual NULLs
    set_clauses = [f"{col} = NULLIF({col}, 'NULL')" for col in columns]

    # Process in batches to avoid timeout
    batch_size = 10
    for i in range(0, len(set_clauses), batch_size):
        batch = set_clauses[i:i + batch_size]
        sql = f"UPDATE dbo.facilities SET {', '.join(batch)}"
        cursor.execute(sql)
        log(f"  Cleaned columns {i + 1}-{min(i + batch_size, len(columns))} of {len(columns)}")

    log(f"Converted 'NULL' strings in {len(columns)} columns")

def add_indexes_and_columns(cursor):
    """Add identity column, timestamps, and indexes after bulk load."""
    log("Adding identity column, timestamps, and indexes...")

    # Add id column as identity
    cursor.execute("""
        ALTER TABLE dbo.facilities ADD id INT IDENTITY(1,1) NOT NULL;
        ALTER TABLE dbo.facilities ADD CONSTRAINT PK_facilities PRIMARY KEY (id);
    """)

    # Add timestamp columns
    cursor.execute("""
        ALTER TABLE dbo.facilities ADD created_at DATETIME DEFAULT GETDATE() NOT NULL;
        ALTER TABLE dbo.facilities ADD updated_at DATETIME DEFAULT GETDATE() NOT NULL;
    """)

    # Create indexes
    cursor.execute("""
        CREATE INDEX idx_facilities_rasclientid ON dbo.facilities(RASCLIENTID);
        CREATE INDEX idx_facilities_compname ON dbo.facilities(COMPNAME);
        CREATE INDEX idx_facilities_city_state ON dbo.facilities(CITY, STATE);
        CREATE INDEX idx_facilities_status ON dbo.facilities(STATUS);
        CREATE INDEX idx_facilities_externalclientid ON dbo.facilities(EXTERNALCLIENTID);
    """)
    log("Indexes created")

def main():
    print("=" * 60)
    print("Facilities BULK INSERT Script")
    print("=" * 60)
    print(f"SQL Server: {SQL_SERVER}")
    print(f"Database: {SQL_DATABASE}")
    print(f"Storage: {STORAGE_ACCOUNT}/{CONTAINER_NAME}")
    print(f"CSV File: {CSV_FILE}")
    print("=" * 60)

    total_start = time.time()

    try:
        # Step 1: Upload CSV to blob storage
        sas_token = upload_csv_to_blob()

        # Step 2: Connect to SQL
        log("Connecting to Azure SQL Database...")
        conn = get_sql_connection()
        cursor = conn.cursor()
        log("Connected successfully!")

        # Step 3: Setup database objects
        setup_database_objects(cursor, sas_token)
        conn.commit()

        # Step 4: Create table
        create_facilities_table(cursor)
        conn.commit()

        # Step 5: Run BULK INSERT
        bulk_time = run_bulk_insert(cursor)
        conn.commit()

        # Step 6: Clean up 'NULL' strings
        cleanup_null_strings(cursor)
        conn.commit()

        # Step 7: Add indexes and additional columns
        add_indexes_and_columns(cursor)
        conn.commit()

        # Verify
        cursor.execute("SELECT COUNT(*) FROM dbo.facilities")
        count = cursor.fetchone()[0]

        total_elapsed = time.time() - total_start
        rows_per_sec = count / bulk_time if bulk_time > 0 else 0

        log(f"Verification: {count} rows in facilities table")
        log(f"BULK INSERT rate: {rows_per_sec:.0f} rows/sec")

        # Sample data
        print("\nSample data (first 3 rows):")
        cursor.execute("SELECT TOP 3 id, RASCLIENTID, COMPNAME, CITY, STATE, STATUS FROM dbo.facilities")
        for row in cursor.fetchall():
            print(f"  {row}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 60)
        print(f"BULK INSERT completed successfully!")
        print(f"Total time: {total_elapsed:.2f}s")
        print(f"Rows imported: {count}")
        print("=" * 60)

    except Exception as e:
        log(f"Error: {e}")
        raise

if __name__ == "__main__":
    main()
