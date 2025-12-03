# Future Improvements

## Zero-Downtime Deployments

### Current State
- **Tier:** B1 Basic ($13/month)
- **Deployment:** Direct to production with ~60-90s restart window
- **Workers:** 2 gunicorn workers via Dockerfile

### Why It's Not Enabled Yet
Attempted S1 Standard tier with staging slot deployment but encountered memory constraints:
- S1 has 1.75GB RAM
- Running production + staging containers simultaneously caused memory exhaustion
- Containers hung indefinitely during swap attempts

### Requirements for Zero-Downtime
To enable staging slot swap deployments:

| Tier | RAM | Cost | Supports Slots |
|------|-----|------|----------------|
| B1 Basic | 1.75GB | ~$13/mo | No |
| S1 Standard | 1.75GB | ~$70/mo | Yes (but insufficient RAM) |
| **S2 Standard** | **3.5GB** | **~$140/mo** | **Yes (recommended)** |
| P1v2 Premium | 3.5GB | ~$150/mo | Yes |
| P2v2 Premium | 7GB | ~$300/mo | Yes |

### Implementation Steps (When Ready)

1. **Upgrade App Service Plan**
   ```bash
   az appservice plan update --name docintel-plan --resource-group DocIntel-rg --sku S2
   ```

2. **Create Staging Slot**
   ```bash
   az webapp deployment slot create \
     --name mvd-docintel-app \
     --resource-group DocIntel-rg \
     --slot staging \
     --configuration-source mvd-docintel-app
   ```

3. **Assign Managed Identity to Staging**
   ```bash
   STAGING_IDENTITY=$(az webapp identity assign \
     --name mvd-docintel-app \
     --resource-group DocIntel-rg \
     --slot staging \
     --query principalId -o tsv)
   ```

4. **Grant Key Vault Access to Staging**
   ```bash
   az role assignment create \
     --assignee-object-id $STAGING_IDENTITY \
     --assignee-principal-type ServicePrincipal \
     --role "Key Vault Secrets User" \
     --scope "/subscriptions/{subscription-id}/resourceGroups/MVD-Core-RG/providers/Microsoft.KeyVault/vaults/kv-miravista-core"
   ```

5. **Update GitHub Actions Workflow**
   Replace direct deployment with slot-based deployment:
   ```yaml
   - name: Deploy to Staging Slot
     run: |
       az webapp config container set \
         --name mvd-docintel-app \
         --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
         --slot staging \
         --container-image-name ${{ env.ACR_NAME }}.azurecr.io/${{ env.IMAGE_NAME }}:${{ github.sha }}

   - name: Wait for Staging Health
     run: |
       # Poll staging health endpoint until 200

   - name: Swap to Production
     run: |
       az webapp deployment slot swap \
         --name mvd-docintel-app \
         --resource-group ${{ secrets.AZURE_RESOURCE_GROUP }} \
         --slot staging \
         --target-slot production
   ```

### Benefits
- Zero downtime during deployments
- Instant rollback by swapping back
- Pre-warm staging before swap
- Test in production-like environment before going live
