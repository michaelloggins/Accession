# Azure Deployment Guide - DocIntelligence

This guide walks through deploying DocIntelligence to Azure using your existing resource groups.

## Resource Groups

| Resource Group | Purpose |
|---------------|---------|
| **DocIntel-OAI** | Application-specific resources (App Service, Storage, SQL) |
| **MVD-Core-RG** | Shared resources (Key Vault: `kv-miravista-core`) |

## Prerequisites

1. Azure CLI installed and logged in
2. GitHub repository created at `https://github.com/michaelloggins/DocIntelligence`
3. Access to both resource groups

## Step 1: Create Azure SQL Serverless Database

```bash
# Variables
RESOURCE_GROUP="DocIntel-OAI"
SQL_SERVER_NAME="docintel-sql"
SQL_DB_NAME="docintel-db"
LOCATION="eastus"  # Adjust as needed
SQL_ADMIN="sqladmin"

# Create SQL Server
az sql server create \
  --name $SQL_SERVER_NAME \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --admin-user $SQL_ADMIN \
  --admin-password "<YOUR_SECURE_PASSWORD>"

# Create Serverless Database (auto-pause after 1 hour, min 0.5 vCores)
az sql db create \
  --resource-group $RESOURCE_GROUP \
  --server $SQL_SERVER_NAME \
  --name $SQL_DB_NAME \
  --edition GeneralPurpose \
  --family Gen5 \
  --compute-model Serverless \
  --min-capacity 0.5 \
  --capacity 1 \
  --auto-pause-delay 60

# Allow Azure services to access SQL Server
az sql server firewall-rule create \
  --resource-group $RESOURCE_GROUP \
  --server $SQL_SERVER_NAME \
  --name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

## Step 2: Create Azure Storage Account

```bash
STORAGE_ACCOUNT="docintelstore"  # Must be globally unique, lowercase, no hyphens

az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS \
  --kind StorageV2 \
  --https-only true \
  --min-tls-version TLS1_2

# Create container for documents
az storage container create \
  --name documents \
  --account-name $STORAGE_ACCOUNT \
  --public-access off
```

## Step 3: Create App Service

```bash
APP_SERVICE_PLAN="docintel-plan"
WEBAPP_NAME="docintel-webapp"  # Must be globally unique

# Create App Service Plan (B1 for dev, P1v2+ for production)
az appservice plan create \
  --name $APP_SERVICE_PLAN \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku B1 \
  --is-linux

# Create Web App
az webapp create \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --plan $APP_SERVICE_PLAN \
  --runtime "PYTHON:3.11"

# Enable system-assigned managed identity
az webapp identity assign \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP
```

## Step 4: Configure Key Vault Access

Grant the App Service access to the shared Key Vault:

```bash
# Get the App Service's managed identity principal ID
PRINCIPAL_ID=$(az webapp identity show \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

# Grant access to Key Vault
az keyvault set-policy \
  --name kv-miravista-core \
  --resource-group MVD-Core-RG \
  --object-id $PRINCIPAL_ID \
  --secret-permissions get list
```

## Step 5: Add Secrets to Key Vault

Add the following secrets to `kv-miravista-core`:

```bash
KV_NAME="kv-miravista-core"

# Database connection string
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "docintel-db-connection" \
  --value "mssql+pyodbc://sqladmin:PASSWORD@docintel-sql.database.windows.net/docintel-db?driver=ODBC+Driver+17+for+SQL+Server"

# JWT Secret
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "docintel-jwt-secret" \
  --value "$(openssl rand -base64 32)"

# App Secret Key
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "docintel-secret-key" \
  --value "$(openssl rand -base64 32)"

# PHI Encryption Key (for encrypting sensitive data)
az keyvault secret set \
  --vault-name $KV_NAME \
  --name "phi-encryption-key" \
  --value "$(openssl rand -base64 32)"
```

## Step 6: Configure App Service Settings

```bash
# Get storage connection string
STORAGE_CONN=$(az storage account show-connection-string \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query connectionString -o tsv)

# Get SQL connection string
SQL_SERVER_FQDN="$SQL_SERVER_NAME.database.windows.net"

# Configure app settings
az webapp config appsettings set \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    ENVIRONMENT="development" \
    DEBUG="false" \
    DATABASE_URL="mssql+pyodbc://sqladmin:PASSWORD@${SQL_SERVER_FQDN}/docintel-db?driver=ODBC+Driver+17+for+SQL+Server" \
    AZURE_STORAGE_CONNECTION_STRING="$STORAGE_CONN" \
    AZURE_STORAGE_CONTAINER="documents" \
    AZURE_KEY_VAULT_URL="https://kv-miravista-core.vault.azure.net/" \
    AZURE_OPENAI_ENDPOINT="<YOUR_OPENAI_ENDPOINT>" \
    AZURE_OPENAI_API_KEY="<YOUR_OPENAI_KEY>" \
    AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4o" \
    AZURE_OPENAI_API_VERSION="2024-02-15-preview" \
    JWT_SECRET_KEY="@Microsoft.KeyVault(SecretUri=https://kv-miravista-core.vault.azure.net/secrets/docintel-jwt-secret/)" \
    SECRET_KEY="@Microsoft.KeyVault(SecretUri=https://kv-miravista-core.vault.azure.net/secrets/docintel-secret-key/)" \
    ALLOWED_ORIGINS='["https://docintel-webapp.azurewebsites.net"]' \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true"

# Set startup command
az webapp config set \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --startup-file "gunicorn --bind=0.0.0.0 --workers=4 --timeout=120 app.main:app -k uvicorn.workers.UvicornWorker"
```

## Step 7: Set Up GitHub Actions

### Create Azure Service Principal

```bash
# Create service principal for GitHub Actions
az ad sp create-for-rbac \
  --name "github-docintel-deploy" \
  --role contributor \
  --scopes /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/DocIntel-OAI \
  --sdk-auth
```

Copy the JSON output - this is your `AZURE_CREDENTIALS` secret.

### Add GitHub Secrets

In your GitHub repository, go to Settings → Secrets and Variables → Actions, and add:

| Secret Name | Value |
|------------|-------|
| `AZURE_CREDENTIALS` | JSON output from service principal creation |
| `AZURE_RESOURCE_GROUP` | `DocIntel-OAI` |

### Update Workflow

Update `.github/workflows/azure-deploy.yml`:
- Set `AZURE_WEBAPP_NAME` to your actual webapp name

## Step 8: Deploy

### Option A: GitHub Actions (Recommended)

Push to main branch:
```bash
git add .
git commit -m "Initial Azure deployment setup"
git push origin main
```

### Option B: Manual Deployment

```bash
# Zip deployment
zip -r deploy.zip . -x ".git/*" -x "venv/*" -x "__pycache__/*" -x "*.pyc"

az webapp deployment source config-zip \
  --name $WEBAPP_NAME \
  --resource-group $RESOURCE_GROUP \
  --src deploy.zip
```

## Step 9: Run Database Migrations

After deployment, SSH into the App Service or use the Kudu console:

```bash
# Via Azure CLI
az webapp ssh --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP

# Then run migrations
cd /home/site/wwwroot
alembic upgrade head
```

Or create a post-deployment script in `.deployment`:
```
[config]
command = bash deploy.sh
```

And `deploy.sh`:
```bash
#!/bin/bash
pip install -r requirements.txt
alembic upgrade head
```

## Step 10: Verify Deployment

1. Visit `https://<WEBAPP_NAME>.azurewebsites.net/health`
2. Check Application Insights for any errors
3. Test login functionality

## Cost Estimates (Development)

| Resource | SKU | Est. Monthly Cost |
|----------|-----|------------------|
| Azure SQL Serverless | GP_S_Gen5_1 | $5-15 (auto-pause) |
| App Service | B1 | ~$13 |
| Storage | Standard LRS | ~$1 |
| Key Vault | Standard | ~$0.03/operation |
| **Total** | | **~$20-30/month** |

## Troubleshooting

### Database Connection Issues

If the app can't connect after serverless auto-pause:
- First request may take 60+ seconds (wake-up time)
- Check connection string format
- Verify firewall rules allow Azure services

### Deployment Failures

```bash
# Check deployment logs
az webapp log deployment show --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP

# Stream live logs
az webapp log tail --name $WEBAPP_NAME --resource-group $RESOURCE_GROUP
```

### Key Vault Access Denied

Verify managed identity has access:
```bash
az keyvault show --name kv-miravista-core --query "properties.accessPolicies"
```

## Next Steps

1. [ ] Configure custom domain and SSL certificate
2. [ ] Set up Azure AD authentication (optional)
3. [ ] Configure backup and disaster recovery
4. [ ] Set up alerts in Application Insights
5. [ ] Enable staging slot for zero-downtime deployments
