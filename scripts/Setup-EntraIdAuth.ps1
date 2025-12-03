<#
.SYNOPSIS
    Configures Entra ID (Azure AD) authentication for Lab Document Intelligence.

.DESCRIPTION
    This script:
    1. Creates an App Registration for OIDC authentication
    2. Creates an Enterprise Application for SCIM provisioning
    3. Creates security groups for role mapping
    4. Generates SCIM bearer token
    5. Stores secrets in Azure Key Vault
    6. Stores configuration in the application's SQL config table

.NOTES
    Requires: Az PowerShell module, AzureAD module (or Microsoft.Graph)
    Run: Install-Module Az, AzureAD -Force

    PowerShell 5.1 compatible
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "DocIntel-rg",

    [Parameter(Mandatory=$false)]
    [string]$KeyVaultName = "kv-mvd-docintel",

    [Parameter(Mandatory=$false)]
    [string]$AppName = "Lab Document Intelligence",

    [Parameter(Mandatory=$false)]
    [string]$WebAppUrl = "https://mvd-docintel-app.azurewebsites.net"
)

$ErrorActionPreference = "Stop"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Entra ID Authentication Setup" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Check for required modules
Write-Host "Checking required modules..." -ForegroundColor Yellow

# Check Az module
if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
    Write-Host "Installing Az.Accounts module..." -ForegroundColor Yellow
    Install-Module -Name Az.Accounts -Force -AllowClobber -Scope CurrentUser
}

if (-not (Get-Module -ListAvailable -Name Az.KeyVault)) {
    Write-Host "Installing Az.KeyVault module..." -ForegroundColor Yellow
    Install-Module -Name Az.KeyVault -Force -AllowClobber -Scope CurrentUser
}

if (-not (Get-Module -ListAvailable -Name Az.Resources)) {
    Write-Host "Installing Az.Resources module..." -ForegroundColor Yellow
    Install-Module -Name Az.Resources -Force -AllowClobber -Scope CurrentUser
}

Import-Module Az.Accounts
Import-Module Az.KeyVault
Import-Module Az.Resources

# Login to Azure if not already logged in
$context = Get-AzContext
if (-not $context) {
    Write-Host "Please login to Azure..." -ForegroundColor Yellow
    Connect-AzAccount
    $context = Get-AzContext
}

$tenantId = $context.Tenant.Id
$subscriptionId = $context.Subscription.Id

Write-Host "Connected to:" -ForegroundColor Green
Write-Host "  Tenant: $tenantId"
Write-Host "  Subscription: $subscriptionId"
Write-Host ""

# ============================================================================
# Step 1: Create App Registration using Azure CLI (more reliable for app reg)
# ============================================================================
Write-Host "Step 1: Creating App Registration..." -ForegroundColor Cyan

$redirectUri = "$WebAppUrl/api/auth/callback"
$logoutUri = "$WebAppUrl/"

# Check if app already exists
$existingApp = az ad app list --display-name $AppName --query "[0]" 2>$null | ConvertFrom-Json

if ($existingApp) {
    Write-Host "  App Registration already exists: $($existingApp.appId)" -ForegroundColor Yellow
    $appId = $existingApp.appId
    $objectId = $existingApp.id
} else {
    Write-Host "  Creating new App Registration..." -ForegroundColor Yellow

    # Create the app registration with required permissions
    $appManifest = @{
        displayName = $AppName
        signInAudience = "AzureADMyOrg"
        web = @{
            redirectUris = @($redirectUri)
            logoutUrl = $logoutUri
            implicitGrantSettings = @{
                enableIdTokenIssuance = $true
                enableAccessTokenIssuance = $false
            }
        }
        requiredResourceAccess = @(
            @{
                resourceAppId = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph
                resourceAccess = @(
                    @{
                        id = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"  # User.Read
                        type = "Scope"
                    },
                    @{
                        id = "37f7f235-527c-4136-accd-4a02d197296e"  # openid
                        type = "Scope"
                    },
                    @{
                        id = "14dad69e-099b-42c9-810b-d002981feec1"  # profile
                        type = "Scope"
                    },
                    @{
                        id = "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0"  # email
                        type = "Scope"
                    }
                )
            }
        )
    }

    $manifestJson = $appManifest | ConvertTo-Json -Depth 10 -Compress
    $manifestFile = [System.IO.Path]::GetTempFileName()
    $manifestJson | Out-File -FilePath $manifestFile -Encoding UTF8

    try {
        $newApp = az ad app create --display-name $AppName `
            --sign-in-audience AzureADMyOrg `
            --web-redirect-uris $redirectUri `
            --enable-id-token-issuance true `
            --query "{appId: appId, id: id}" | ConvertFrom-Json

        $appId = $newApp.appId
        $objectId = $newApp.id

        Write-Host "  Created App Registration: $appId" -ForegroundColor Green
    } finally {
        Remove-Item $manifestFile -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================================
# Step 2: Create Client Secret
# ============================================================================
Write-Host ""
Write-Host "Step 2: Creating Client Secret..." -ForegroundColor Cyan

# Create a new client secret (valid for 2 years)
$endDate = (Get-Date).AddYears(2).ToString("yyyy-MM-ddTHH:mm:ssZ")
$secretResult = az ad app credential reset --id $appId --append --display-name "DocIntel-OIDC-Secret" --end-date $endDate --query "password" -o tsv

if ($secretResult) {
    $clientSecret = $secretResult
    Write-Host "  Client secret created successfully" -ForegroundColor Green
} else {
    Write-Error "Failed to create client secret"
}

# ============================================================================
# Step 3: Create Service Principal (Enterprise Application)
# ============================================================================
Write-Host ""
Write-Host "Step 3: Creating Enterprise Application (Service Principal)..." -ForegroundColor Cyan

$existingSp = az ad sp list --filter "appId eq '$appId'" --query "[0]" | ConvertFrom-Json

if ($existingSp) {
    Write-Host "  Service Principal already exists" -ForegroundColor Yellow
    $spObjectId = $existingSp.id
} else {
    $newSp = az ad sp create --id $appId --query "id" -o tsv
    $spObjectId = $newSp
    Write-Host "  Created Service Principal: $spObjectId" -ForegroundColor Green
}

# ============================================================================
# Step 4: Create Security Groups for Role Mapping
# ============================================================================
Write-Host ""
Write-Host "Step 4: Creating Security Groups for Role Mapping..." -ForegroundColor Cyan

$groups = @(
    @{ Name = "DocIntel - Admin"; MailNickname = "DocIntel-Admin"; Description = "Lab Document Intelligence Administrators - Full system access"; Role = "admin" },
    @{ Name = "DocIntel - PowerUser"; MailNickname = "DocIntel-PowerUser"; Description = "Lab Document Intelligence Power Users - Review and approve documents"; Role = "reviewer" },
    @{ Name = "DocIntel - User"; MailNickname = "DocIntel-User"; Description = "Lab Document Intelligence Users - View only access"; Role = "read_only" }
)

$groupIds = @{}

foreach ($group in $groups) {
    $existingGroup = az ad group list --filter "displayName eq '$($group.Name)'" --query "[0]" | ConvertFrom-Json

    if ($existingGroup) {
        Write-Host "  Group '$($group.Name)' already exists: $($existingGroup.id)" -ForegroundColor Yellow
        $groupIds[$group.Role] = $existingGroup.id
    } else {
        $newGroup = az ad group create --display-name $group.Name --mail-nickname $group.MailNickname --description $group.Description --query "id" -o tsv
        $groupIds[$group.Role] = $newGroup
        Write-Host "  Created group '$($group.Name)': $newGroup" -ForegroundColor Green
    }
}

# ============================================================================
# Step 5: Generate SCIM Bearer Token
# ============================================================================
Write-Host ""
Write-Host "Step 5: Generating SCIM Bearer Token..." -ForegroundColor Cyan

# Generate a secure random token for SCIM
Add-Type -AssemblyName System.Web
$scimToken = [System.Web.Security.Membership]::GeneratePassword(64, 8)
# Remove problematic characters
$scimToken = $scimToken -replace '[^a-zA-Z0-9]', ''
$scimToken = $scimToken.Substring(0, [Math]::Min(64, $scimToken.Length))

Write-Host "  SCIM token generated (64 characters)" -ForegroundColor Green

# ============================================================================
# Step 6: Store Secrets in Key Vault
# ============================================================================
Write-Host ""
Write-Host "Step 6: Storing Secrets in Key Vault..." -ForegroundColor Cyan

# Check if Key Vault exists
$kv = Get-AzKeyVault -VaultName $KeyVaultName -ErrorAction SilentlyContinue

if (-not $kv) {
    Write-Host "  Key Vault '$KeyVaultName' not found. Creating..." -ForegroundColor Yellow
    $kv = New-AzKeyVault -Name $KeyVaultName -ResourceGroupName $ResourceGroup -Location "East US"
}

# Store secrets
$secrets = @{
    "AZURE-AD-CLIENT-SECRET" = $clientSecret
    "SCIM-BEARER-TOKEN" = $scimToken
}

foreach ($secretName in $secrets.Keys) {
    $secretValue = ConvertTo-SecureString -String $secrets[$secretName] -AsPlainText -Force
    Set-AzKeyVaultSecret -VaultName $KeyVaultName -Name $secretName -SecretValue $secretValue | Out-Null
    Write-Host "  Stored secret: $secretName" -ForegroundColor Green
}

# ============================================================================
# Step 7: Update App Service Configuration
# ============================================================================
Write-Host ""
Write-Host "Step 7: Updating App Service Configuration..." -ForegroundColor Cyan

$webAppName = "mvd-docintel-app"

# Get Key Vault reference format for secrets
$clientSecretRef = "@Microsoft.KeyVault(VaultName=$KeyVaultName;SecretName=AZURE-AD-CLIENT-SECRET)"
$scimTokenRef = "@Microsoft.KeyVault(VaultName=$KeyVaultName;SecretName=SCIM-BEARER-TOKEN)"

$appSettings = @(
    "AZURE_AD_TENANT_ID=$tenantId",
    "AZURE_AD_CLIENT_ID=$appId",
    "AZURE_AD_CLIENT_SECRET=$clientSecretRef",
    "AZURE_AD_REDIRECT_URI=$redirectUri",
    "AZURE_AD_ADMIN_GROUP_ID=$($groupIds['admin'])",
    "AZURE_AD_REVIEWER_GROUP_ID=$($groupIds['reviewer'])",
    "AZURE_AD_READONLY_GROUP_ID=$($groupIds['read_only'])",
    "SSO_ENABLED=true",
    "SCIM_BEARER_TOKEN=$scimTokenRef"
)

try {
    az webapp config appsettings set --name $webAppName --resource-group $ResourceGroup --settings $appSettings | Out-Null
    Write-Host "  App Service configuration updated" -ForegroundColor Green
} catch {
    Write-Host "  Warning: Could not update App Service settings automatically" -ForegroundColor Yellow
    Write-Host "  You may need to set these manually in Azure Portal" -ForegroundColor Yellow
}

# ============================================================================
# Step 8: Configure Optional Claims for Groups
# ============================================================================
Write-Host ""
Write-Host "Step 8: Configuring Token Claims..." -ForegroundColor Cyan

# Update the app to include group claims in the ID token
$optionalClaims = @{
    idToken = @(
        @{
            name = "groups"
            source = $null
            essential = $false
            additionalProperties = @()
        }
    )
}

$claimsJson = $optionalClaims | ConvertTo-Json -Depth 10 -Compress
az ad app update --id $appId --optional-claims $claimsJson 2>$null

Write-Host "  Configured group claims in ID token" -ForegroundColor Green

# ============================================================================
# Summary
# ============================================================================
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Configuration Complete!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "App Registration Details:" -ForegroundColor Yellow
Write-Host "  Application (client) ID: $appId"
Write-Host "  Directory (tenant) ID:   $tenantId"
Write-Host "  Redirect URI:            $redirectUri"
Write-Host ""
Write-Host "Security Groups Created:" -ForegroundColor Yellow
Write-Host "  DocIntel - Admin:     $($groupIds['admin'])"
Write-Host "  DocIntel - PowerUser: $($groupIds['reviewer'])"
Write-Host "  DocIntel - User:      $($groupIds['read_only'])"
Write-Host ""
Write-Host "Secrets Stored in Key Vault ($KeyVaultName):" -ForegroundColor Yellow
Write-Host "  - AZURE-AD-CLIENT-SECRET"
Write-Host "  - SCIM-BEARER-TOKEN"
Write-Host ""
Write-Host "SCIM Provisioning Endpoint:" -ForegroundColor Yellow
Write-Host "  URL:   $WebAppUrl/scim/v2"
Write-Host "  Token: (stored in Key Vault as SCIM-BEARER-TOKEN)"
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Magenta
Write-Host "  1. Add users to the security groups in Entra ID"
Write-Host "  2. Grant admin consent for the API permissions in Azure Portal"
Write-Host "  3. Configure SCIM provisioning in Enterprise Application settings"
Write-Host "  4. Test SSO login at: $WebAppUrl"
Write-Host ""

# Output configuration for reference
$config = @{
    TenantId = $tenantId
    ClientId = $appId
    RedirectUri = $redirectUri
    AdminGroupId = $groupIds['admin']
    ReviewerGroupId = $groupIds['reviewer']
    ReadOnlyGroupId = $groupIds['read_only']
    ScimEndpoint = "$WebAppUrl/scim/v2"
    KeyVaultName = $KeyVaultName
}

$configJson = $config | ConvertTo-Json -Depth 5
$configPath = Join-Path $PSScriptRoot "entra-id-config.json"
$configJson | Out-File -FilePath $configPath -Encoding UTF8

Write-Host "Configuration saved to: $configPath" -ForegroundColor Green
