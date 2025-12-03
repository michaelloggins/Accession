"""
Script to import facilities data from RASCLIENTS.csv into Azure SQL Server.
This script will:
1. Alter the facilities table to match the CSV schema
2. Import all data from the CSV file

Uses fast_executemany for bulk insert performance.
"""
import csv
import pyodbc
import struct
import time
from datetime import datetime
from azure.identity import AzureCliCredential

# Azure SQL connection string
SERVER = 'mvd-docintel-sql.database.windows.net'
DATABASE = 'docintel-db'
DRIVER = '{ODBC Driver 18 for SQL Server}'

# CSV file path
CSV_FILE = r'C:\Projects\DocIntelligence\RASCLIENTS.csv'

def get_connection():
    """Get Azure SQL connection using Azure CLI credential with ODBC Driver 18."""
    # Get token using Azure CLI credential (uses az login session)
    credential = AzureCliCredential()
    token = credential.get_token("https://database.windows.net/.default")

    # Prepare access token for ODBC
    token_bytes = token.token.encode("UTF-16-LE")
    token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
    SQL_COPT_SS_ACCESS_TOKEN = 1256

    conn_str = (
        f'DRIVER={DRIVER};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
    )
    conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})
    return conn

def alter_table(cursor):
    """Drop and recreate the facilities table with new schema."""

    # Drop existing table (with foreign key handling)
    print("Dropping existing facilities table...")

    # First check if table exists and drop foreign key constraints
    cursor.execute("""
        DECLARE @sql NVARCHAR(MAX) = N'';

        -- Drop foreign key constraints referencing facilities
        SELECT @sql += 'ALTER TABLE ' + QUOTENAME(OBJECT_SCHEMA_NAME(parent_object_id))
            + '.' + QUOTENAME(OBJECT_NAME(parent_object_id))
            + ' DROP CONSTRAINT ' + QUOTENAME(name) + ';'
        FROM sys.foreign_keys
        WHERE referenced_object_id = OBJECT_ID('dbo.facilities');

        EXEC sp_executesql @sql;
    """)

    # Drop the table if exists
    cursor.execute("""
        IF OBJECT_ID('dbo.facilities', 'U') IS NOT NULL
            DROP TABLE dbo.facilities;
    """)

    print("Creating new facilities table with CSV schema...")

    # Create new table matching CSV columns exactly
    cursor.execute("""
        CREATE TABLE dbo.facilities (
            id INT IDENTITY(1,1) PRIMARY KEY,
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
            START_DATE DATETIME NULL,
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
            PANEL_PRELIMINARY NVARCHAR(10) NULL,
            updated_at DATETIME DEFAULT GETDATE() NOT NULL,
            created_at DATETIME DEFAULT GETDATE() NOT NULL
        );

        -- Create indexes for commonly queried fields
        CREATE INDEX idx_facilities_rasclientid ON dbo.facilities(RASCLIENTID);
        CREATE INDEX idx_facilities_compname ON dbo.facilities(COMPNAME);
        CREATE INDEX idx_facilities_city_state ON dbo.facilities(CITY, STATE);
        CREATE INDEX idx_facilities_status ON dbo.facilities(STATUS);
        CREATE INDEX idx_facilities_externalclientid ON dbo.facilities(EXTERNALCLIENTID);
    """)

    print("Table created successfully!")

def clean_value(value):
    """Clean a value from CSV - convert NULL strings to None, handle empty strings."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.upper() == 'NULL' or value == '':
            return None
    return value

def parse_datetime(value):
    """Parse datetime value from CSV."""
    value = clean_value(value)
    if value is None:
        return None
    try:
        # Handle format like "2025-04-25 00:00:00.000"
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None

def parse_int(value):
    """Parse integer value from CSV."""
    value = clean_value(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None

def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {message}", flush=True)

def import_data(cursor):
    """Import data from CSV file using fast_executemany for bulk performance."""
    log(f"Reading CSV file: {CSV_FILE}")

    # Enable fast_executemany for bulk insert performance
    cursor.fast_executemany = True
    log("Enabled fast_executemany for bulk insert optimization")

    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        # Get column names from header
        columns = reader.fieldnames
        log(f"Found {len(columns)} columns in CSV")

        # Prepare insert statement
        insert_sql = """
            INSERT INTO dbo.facilities (
                ORIGREC, ADRESS, ADRESS_A, CATEGORY, CITY, COMPNAME, COUNTRY, COUNTY,
                DEFAULTCONTACT, EXTERNALCLIENTID, HL7_ID, ORIGSTS, POB, PRIMARYFAX,
                PRIMARYPHONE, RASCLIENTID, STATE, UDPARAM0, UDPARAM1, UDPARAM2,
                UDPARAM3, UDPARAM4, URL, VMDPATH, ZIP, OWNER, EMAIL, ACCOUNT_NAME,
                DELINQUENT, ORGANIZATIONAL_OID, APPLICATION_OID_PROD, DEV_INBOUND_RESULTS,
                DEV_OUTBOUND_ORDERS, DEV_OUTBOUND_RESULTS, DEV_INBOUND_ORDERS,
                APPLICATION_OID_DEV, PROD_INBOUND_ORDERS, PROD_INBOUND_RESULTS,
                PROD_OUTBOUND_ORDERS, PROD_OUTBOUND_RESULTS, HL7_CONTACT, HL7_CONTACT_PHONE,
                HL7_CONTACT_EMAIL, DEV_APPLICATION_NAME, PROD_APPLICATION_NAME, STATUS,
                START_DATE, PRICELISTID, JURISDICTION_TYPE, JURISDICTION_CODE, CLIENT_USAGE,
                NETWORK_SHARED_PATH, SECONDARYPHONE, PHONEEXTENSION1, PHONEEXTENSION2,
                PAGERCELL, FAXCOUNTRYCODE, FAXAREACODE, FAXLOCALNUMBER, PHONECOUNTRYCODE,
                PHONEAREACODE, PHONELOCALNUMBER, LABDIRECTORDEGREE, IS_PRIMARY, DEPARTMENT,
                INTERFACE_ID, PANEL_PRELIMINARY
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
        """

        row_count = 0
        batch_size = 1000
        batch = []
        max_rows = 10  # Limit to first 10 records for testing (set to None for full import)
        total_start_time = time.time()
        batch_start_time = time.time()

        log(f"Starting import (batch_size={batch_size}, max_rows={max_rows or 'unlimited'})...")

        for row in reader:
            if max_rows and row_count >= max_rows:
                break
            values = (
                parse_int(row.get('ORIGREC')),
                clean_value(row.get('ADRESS')),
                clean_value(row.get('ADRESS_A')),
                clean_value(row.get('CATEGORY')),
                clean_value(row.get('CITY')),
                clean_value(row.get('COMPNAME')),
                clean_value(row.get('COUNTRY')),
                clean_value(row.get('COUNTY')),
                clean_value(row.get('DEFAULTCONTACT')),
                clean_value(row.get('EXTERNALCLIENTID')),
                clean_value(row.get('HL7_ID')),
                clean_value(row.get('ORIGSTS')),
                clean_value(row.get('POB')),
                clean_value(row.get('PRIMARYFAX')),
                clean_value(row.get('PRIMARYPHONE')),
                clean_value(row.get('RASCLIENTID')),
                clean_value(row.get('STATE')),
                clean_value(row.get('UDPARAM0')),
                clean_value(row.get('UDPARAM1')),
                clean_value(row.get('UDPARAM2')),
                clean_value(row.get('UDPARAM3')),
                clean_value(row.get('UDPARAM4')),
                clean_value(row.get('URL')),
                clean_value(row.get('VMDPATH')),
                clean_value(row.get('ZIP')),
                clean_value(row.get('OWNER')),
                clean_value(row.get('EMAIL')),
                clean_value(row.get('ACCOUNT_NAME')),
                clean_value(row.get('DELINQUENT')),
                clean_value(row.get('ORGANIZATIONAL_OID')),
                clean_value(row.get('APPLICATION_OID_PROD')),
                clean_value(row.get('DEV_INBOUND_RESULTS')),
                clean_value(row.get('DEV_OUTBOUND_ORDERS')),
                clean_value(row.get('DEV_OUTBOUND_RESULTS')),
                clean_value(row.get('DEV_INBOUND_ORDERS')),
                clean_value(row.get('APPLICATION_OID_DEV')),
                clean_value(row.get('PROD_INBOUND_ORDERS')),
                clean_value(row.get('PROD_INBOUND_RESULTS')),
                clean_value(row.get('PROD_OUTBOUND_ORDERS')),
                clean_value(row.get('PROD_OUTBOUND_RESULTS')),
                clean_value(row.get('HL7_CONTACT')),
                clean_value(row.get('HL7_CONTACT_PHONE')),
                clean_value(row.get('HL7_CONTACT_EMAIL')),
                clean_value(row.get('DEV_APPLICATION_NAME')),
                clean_value(row.get('PROD_APPLICATION_NAME')),
                clean_value(row.get('STATUS')),
                parse_datetime(row.get('START_DATE')),
                clean_value(row.get('PRICELISTID')),
                clean_value(row.get('JURISDICTION_TYPE')),
                clean_value(row.get('JURISDICTION_CODE')),
                clean_value(row.get('CLIENT_USAGE')),
                clean_value(row.get('NETWORK_SHARED_PATH')),
                clean_value(row.get('SECONDARYPHONE')),
                clean_value(row.get('PHONEEXTENSION1')),
                clean_value(row.get('PHONEEXTENSION2')),
                clean_value(row.get('PAGERCELL')),
                clean_value(row.get('FAXCOUNTRYCODE')),
                clean_value(row.get('FAXAREACODE')),
                clean_value(row.get('FAXLOCALNUMBER')),
                clean_value(row.get('PHONECOUNTRYCODE')),
                clean_value(row.get('PHONEAREACODE')),
                clean_value(row.get('PHONELOCALNUMBER')),
                clean_value(row.get('LABDIRECTORDEGREE')),
                clean_value(row.get('IS_PRIMARY')),
                clean_value(row.get('DEPARTMENT')),
                clean_value(row.get('INTERFACE_ID')),
                clean_value(row.get('PANEL_PRELIMINARY')),
            )

            batch.append(values)
            row_count += 1

            if len(batch) >= batch_size:
                batch_elapsed = time.time() - batch_start_time
                log(f"Inserting batch of {len(batch)} rows (rows {row_count - len(batch) + 1}-{row_count})...")
                cursor.executemany(insert_sql, batch)
                insert_elapsed = time.time() - batch_start_time - batch_elapsed
                rows_per_sec = len(batch) / insert_elapsed if insert_elapsed > 0 else 0
                log(f"  Batch inserted in {insert_elapsed:.2f}s ({rows_per_sec:.0f} rows/sec) - Total: {row_count} rows")
                batch = []
                batch_start_time = time.time()

        # Insert remaining rows
        if batch:
            log(f"Inserting final batch of {len(batch)} rows...")
            cursor.executemany(insert_sql, batch)
            log(f"  Final batch inserted - Total: {row_count} rows")

        total_elapsed = time.time() - total_start_time
        avg_rows_per_sec = row_count / total_elapsed if total_elapsed > 0 else 0
        log(f"Import complete: {row_count} rows in {total_elapsed:.2f}s ({avg_rows_per_sec:.0f} rows/sec avg)")

def main():
    print("=" * 60)
    print("Facilities Import Script")
    print("=" * 60)
    print(f"Server: {SERVER}")
    print(f"Database: {DATABASE}")
    print(f"CSV File: {CSV_FILE}")
    print("=" * 60)

    try:
        print("\nConnecting to Azure SQL Database...")
        conn = get_connection()
        cursor = conn.cursor()
        print("Connected successfully!")

        # Alter table schema
        alter_table(cursor)
        conn.commit()

        # Import data
        import_data(cursor)
        conn.commit()

        # Verify import
        cursor.execute("SELECT COUNT(*) FROM dbo.facilities")
        count = cursor.fetchone()[0]
        print(f"\nVerification: {count} rows in facilities table")

        # Show sample data
        print("\nSample data (first 3 rows):")
        cursor.execute("SELECT TOP 3 id, RASCLIENTID, COMPNAME, CITY, STATE, STATUS FROM dbo.facilities")
        for row in cursor.fetchall():
            print(f"  {row}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 60)
        print("Import completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nError: {e}")
        raise

if __name__ == "__main__":
    main()
