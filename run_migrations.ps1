$creds = az webapp deployment list-publishing-credentials --name app-accession-dev --resource-group rg-accession-dev | ConvertFrom-Json
$user = $creds.publishingUserName
$pass = $creds.publishingPassword
$pair = "${user}:${pass}"
$bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
$base64 = [Convert]::ToBase64String($bytes)
$headers = @{ Authorization = "Basic $base64"; 'Content-Type' = 'application/json' }
$body = '{"command": "cd /home/site/wwwroot && python -m alembic upgrade head 2>&1", "dir": "/home/site/wwwroot"}'
$response = Invoke-RestMethod -Uri 'https://app-accession-dev.scm.azurewebsites.net/api/command' -Method Post -Headers $headers -Body $body
$response | ConvertTo-Json -Depth 5
