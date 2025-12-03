# DocIntelligence - Deployed Azure Resources

This document lists all Azure resources created for the DocIntelligence application.

## Resource Summary

| Resource | Type | Name | Location |
|----------|------|------|----------|
| Resource Group | Resource Group | DocIntel-rg | East US |
| SQL Server | Azure SQL Server | mvd-docintel-sql | Central US |
| Database | Azure SQL Serverless | docintel-db | Central US |
| Storage Account | Storage Account | mvddocintelstore | Central US |
| App Service Plan | App Service Plan | docintel-plan | Central US |
| Web App | App Service | mvd-docintel-app | Central US |
| OpenAI Service | Cognitive Services | DocIntel-OAI | East US |
| Key Vault (Shared) | Key Vault | kv-miravista-core | Central US |

## Connection Information

### Application URL
- **Production**: https://mvd-docintel-app.azurewebsites.net

### SQL Server
- **Server**: mvd-docintel-sql.database.windows.net
- **Database**: docintel-db
- **Admin User**: sqladmin
- **SKU**: GP_S_Gen5_1 (Serverless, 0.5-1 vCores, auto-pause after 60 min)

### Storage Account
- **Account**: mvddocintelstore
- **Container**: documents
- **Blob Endpoint**: https://mvddocintelstore.blob.core.windows.net/

### Azure OpenAI
- **Endpoint**: https://docintel-oai.openai.azure.com/
- **Deployment**: gpt-4o

## Security Configuration

### HIPAA Compliance Features
- **TLS**: Minimum 1.2 for all services
- **SQL TDE**: Transparent Data Encryption enabled
- **Storage Encryption**: Microsoft-managed keys, blob and file encryption
- **FTPS**: Disabled (HTTPS only)
- **Public Blob Access**: Disabled

### App Service Settings
- **HTTPS Only**: Yes
- **TLS Version**: 1.2+
- **HTTP/2**: Enabled
- **FTP State**: Disabled
- **Managed Identity**: System-assigned (for Key Vault access)

## GitHub Integration

### Repository
- **URL**: https://github.com/michaelloggins/DocIntelligence

### GitHub Actions Secrets Configured
- `AZURE_CREDENTIALS` - Service principal for deployment
- `AZURE_RESOURCE_GROUP` - DocIntel-rg

### CI/CD Workflow
- Push to `main` triggers automatic deployment
- Pull requests deploy to staging (if slot created)

## Cost Estimates (Development)

| Resource | SKU | Est. Monthly Cost |
|----------|-----|------------------|
| Azure SQL Serverless | GP_S_Gen5_1 (auto-pause) | ~$5-15 |
| App Service | B1 (Basic) | ~$13 |
| Storage Account | Standard LRS | ~$0.50 |
| Azure OpenAI | Pay-per-use | Varies |
| **Total** | | **~$20-30/month** |

## Next Steps

1. **Wait for GitHub Actions deployment to complete**
   - Check: https://github.com/michaelloggins/DocIntelligence/actions

2. **Run database migrations** (after deployment)
   ```bash
   # SSH into App Service
   az webapp ssh --name mvd-docintel-app --resource-group DocIntel-rg

   # Or use Kudu console: https://mvd-docintel-app.scm.azurewebsites.net
   cd site/wwwroot
   alembic upgrade head
   ```

3. **Create initial admin user**
   ```bash
   # After migrations, run seed script
   python seed_user.py
   ```

4. **Test the application**
   - Visit: https://mvd-docintel-app.azurewebsites.net
   - Check health: https://mvd-docintel-app.azurewebsites.net/health

## Troubleshooting

### View Application Logs
```bash
az webapp log tail --name mvd-docintel-app --resource-group DocIntel-rg
```

### Check Deployment Logs
```bash
az webapp log deployment show --name mvd-docintel-app --resource-group DocIntel-rg
```

### Database Wake-up
The serverless database auto-pauses after 60 minutes of inactivity. First request after pause may take 30-60 seconds while it resumes.

### Key Vault Access
The App Service has `Key Vault Secrets User` role on `kv-miravista-core`. To add secrets:
```bash
# You'll need Key Vault Secrets Officer role to add secrets
az keyvault secret set --vault-name kv-miravista-core --name "secret-name" --value "secret-value"
```
