# GitHub Actions Secrets

Add these in GitHub: `Settings -> Secrets and variables -> Actions`.

## Backend

`AZURE_CREDENTIALS`

```json
{
  "clientId": "<service-principal-client-id>",
  "clientSecret": "<service-principal-secret>",
  "subscriptionId": "<azure-subscription-id>",
  "tenantId": "<azure-tenant-id>"
}
```

Create it with:

```powershell
az ad sp create-for-rbac `
  --name "sp-car-legalizer-github" `
  --role contributor `
  --scopes /subscriptions/<subscription-id>/resourceGroups/rg-car-legalizer-demo `
  --sdk-auth
```

Other backend secrets:

- `AZURE_RESOURCE_GROUP`
- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `CONTAINER_APP_NAME`

## Frontend

- `AZURE_STATIC_WEB_APPS_API_TOKEN`
- `VITE_API_BASE_URL`
- `VITE_AUTH_CLIENT_ID`
- `VITE_AUTH_AUTHORITY`
- `VITE_AUTH_REDIRECT_URI`
- `VITE_API_SCOPE`

For the private demo phase, leave the auth-related `VITE_AUTH_*` values empty so the frontend does not show Microsoft login.
