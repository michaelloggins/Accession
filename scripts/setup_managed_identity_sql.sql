-- Run this script in the accession-dev-db database as the Azure AD admin
-- Connect using Azure Data Studio or SSMS with Azure AD authentication

-- Create a user for the web app's managed identity
-- The name must match the web app name exactly
CREATE USER [app-accession-dev] FROM EXTERNAL PROVIDER;

-- Grant necessary permissions
ALTER ROLE db_datareader ADD MEMBER [app-accession-dev];
ALTER ROLE db_datawriter ADD MEMBER [app-accession-dev];
ALTER ROLE db_ddladmin ADD MEMBER [app-accession-dev];  -- For Alembic migrations

-- Verify the user was created
SELECT name, type_desc, authentication_type_desc
FROM sys.database_principals
WHERE name = 'app-accession-dev';
