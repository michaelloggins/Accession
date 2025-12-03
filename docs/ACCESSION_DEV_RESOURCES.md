# Accession - Development Environment Azure Resources

This document lists all Azure resources created for the Accession development environment.

## Resource Summary

| Resource | Type | Name | Resource Group | Location |
|----------|------|------|----------------|----------|
| Resource Group | Resource Group | rg-accession-dev | - | Central US |
| SQL Database | Azure SQL Serverless | accession-dev-db | DocIntel-rg (shared server) | Central US |
| Storage Account | Storage Account | staccessiondev | rg-accession-dev | Central US |
| App Service Plan | App Service Plan | asp-accession-dev | rg-accession-dev | Central US |
| Web App | App Service | app-accession-dev | rg-accession-dev | Central US |
| Application Insights | Insights | appi-accession-dev | rg-accession-dev | Central US |
| Log Analytics | Workspace | log-accession-dev | rg-accession-dev | Central US |
| Virtual Network | VNet | vnet-accession-dev | rg-accession-dev | Central US |
| Key Vault (Shared) | Key Vault | kv-miravista-core | MVD-Core-RG | Central US |
| OpenAI (Shared) | Cognitive Services | docintel-openai | DocIntel-rg | Central US |

## Shared Resources (from DocIntelligence)

These resources are shared with the DocIntelligence production environment:

- **SQL Server**: `mvd-docintel-sql.database.windows.net` (new database on existing server)
- **Key Vault**: `kv-miravista-core` (new secrets with `accession-dev-` prefix)
- **Azure OpenAI**: `docintel-openai` (same model deployments)

## Connection Information

### Application URL
- **Dev**: https://app-accession-dev.azurewebsites.net

### SQL Server (via Private Endpoint)
- **Server**: mvd-docintel-sql.database.windows.net
- **Database**: accession-dev-db
- **Authentication**: Azure AD Managed Identity
- **Private IP**: 10.1.1.4
- **SKU**: GP_S_Gen5_1 (Serverless, 0.5-1 vCores, auto-pause after 60 min)

### Storage Account (via Private Endpoint)
- **Account**: staccessiondev
- **Container**: documents
- **Blob Endpoint**: https://staccessiondev.blob.core.windows.net/
- **Private IP**: 10.1.1.5

### Azure OpenAI (Shared)
- **Endpoint**: https://docintel-openai.openai.azure.com/
- **Deployment**: gpt-4o

### Key Vault Secrets

| Secret Name | Description |
|-------------|-------------|
| accession-dev-jwt-secret | JWT signing key |
| accession-dev-secret-key | Application secret key |
| accession-dev-storage-connection | Blob storage connection string |
| accession-dev-db-connection | SQL connection string (MSI auth) |
| docintel-openai-api-key | Shared OpenAI API key |

## Network Configuration

### Virtual Network: vnet-accession-dev
- **Address Space**: 10.1.0.0/16

| Subnet | Address Prefix | Purpose |
|--------|----------------|---------|
| snet-private-endpoints | 10.1.1.0/24 | SQL & Blob private endpoints |
| snet-webapp-integration | 10.1.2.0/24 | Web app VNet integration |

### Private Endpoints

| Endpoint | Target | Private IP |
|----------|--------|------------|
| pe-accession-dev-sql | SQL Server | 10.1.1.4 |
| pe-accession-dev-blob | Blob Storage | 10.1.1.5 |

### Private DNS Zones
- `privatelink.database.windows.net` - SQL resolution
- `privatelink.blob.core.windows.net` - Blob resolution

## Security Configuration

### HIPAA Compliance Features
- **TLS**: Minimum 1.2 for all services
- **SQL TDE**: Transparent Data Encryption enabled (inherited from server)
- **Storage Encryption**: Microsoft-managed keys
- **FTPS**: Disabled (HTTPS only)
- **Public Blob Access**: Disabled
- **Private Endpoints**: SQL and Blob storage accessed via VNet

### App Service Settings
- **HTTPS Only**: Yes
- **TLS Version**: 1.2+
- **HTTP/2**: Enabled
- **FTP State**: Disabled
- **Managed Identity**: System-assigned (for Key Vault and SQL access)

## Setup Steps (One-Time)

### 1. Grant SQL Database Access to Managed Identity

Connect to `accession-dev-db` using Azure AD authentication (e.g., Azure Data Studio) and run:

```sql
-- Create user for web app's managed identity
CREATE USER [app-accession-dev] FROM EXTERNAL PROVIDER;

-- Grant permissions for the application
ALTER ROLE db_datareader ADD MEMBER [app-accession-dev];
ALTER ROLE db_datawriter ADD MEMBER [app-accession-dev];
ALTER ROLE db_ddladmin ADD MEMBER [app-accession-dev];  -- For migrations
```

See: `scripts/setup_managed_identity_sql.sql`

### 2. Deploy Application Code

```bash
# Option 1: GitHub Actions (recommended)
# Configure GitHub secrets and push to main branch

# Option 2: Azure CLI
cd C:\Projects\Accession
az webapp deployment source config-zip \
  --name app-accession-dev \
  --resource-group rg-accession-dev \
  --src deploy.zip

# Option 3: Git deployment
az webapp deployment source config-local-git \
  --name app-accession-dev \
  --resource-group rg-accession-dev
```

### 3. Run Database Migrations

After deployment, SSH into the app or use Kudu:

```bash
# Kudu console: https://app-accession-dev.scm.azurewebsites.net
cd site/wwwroot
alembic upgrade head
```

### 4. Seed Initial Data

```bash
python scripts/seed_tests.py
python scripts/seed_species.py
python scripts/seed_user.py
```

## Cost Estimates (Development)

| Resource | SKU | Est. Monthly Cost |
|----------|-----|------------------|
| Azure SQL Serverless | GP_S_Gen5_1 (auto-pause) | ~$5-15 |
| App Service | B1 (Basic) | ~$13 |
| Storage Account | Standard LRS | ~$0.50 |
| Application Insights | Pay-per-GB | ~$2-5 |
| Azure OpenAI | Pay-per-use (shared) | Varies |
| Private Endpoints | 2 × $7.30 | ~$15 |
| **Total** | | **~$35-50/month** |

## Troubleshooting

### View Application Logs
```bash
az webapp log tail --name app-accession-dev --resource-group rg-accession-dev
```

### Check Deployment Logs
```bash
az webapp log deployment show --name app-accession-dev --resource-group rg-accession-dev
```

### Database Wake-up
The serverless database auto-pauses after 60 minutes of inactivity. First request after pause may take 30-60 seconds while it resumes.

### Key Vault Access Issues
Verify the managed identity has `Key Vault Secrets User` role:
```bash
az role assignment list --assignee 0ce6427f-0a6b-4d44-a531-9e9b1d75586a --scope /subscriptions/8d360715-dc0c-4ec3-b879-9e2d1213b76d/resourceGroups/MVD-Core-RG/providers/Microsoft.KeyVault/vaults/kv-miravista-core
```

### Private Endpoint DNS Issues
If the web app can't resolve private endpoints, ensure:
1. VNet integration is active on the web app
2. Private DNS zones are linked to the VNet
3. DNS zone groups are configured on the private endpoints

## GitHub Integration

### Repository
- **URL**: https://github.com/michaelloggins/Accession

### GitHub Actions Secrets (To Configure)
- `AZURE_CREDENTIALS` - Service principal for deployment
- `AZURE_WEBAPP_NAME` - app-accession-dev
- `AZURE_RESOURCE_GROUP` - rg-accession-dev

## Related Documentation
- [Azure Setup Guide](AZURE_SETUP.md)
- [Database Schema](DATABASE_SCHEMA.md)
- [HIPAA Compliance](HIPAA_REMEDIATION_PLAN.md)
