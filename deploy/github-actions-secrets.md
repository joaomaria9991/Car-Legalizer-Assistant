# GitHub Actions Secrets

Add these secrets in GitHub under:

```text
Settings -> Secrets and variables -> Actions
```

## Backend Workflow

```text
AZURE_CREDENTIALS
AZURE_RESOURCE_GROUP
ACR_NAME
ACR_LOGIN_SERVER
CONTAINER_APP_NAME
```

`AZURE_CREDENTIALS` is the JSON output from an Azure service principal:

```powershell
az ad sp create-for-rbac `
  --name "sp-car-legalizer-github" `
  --role contributor `
  --scopes /subscriptions/<subscription-id>/resourceGroups/rg-car-legalizer-demo `
  --sdk-auth
```

## Frontend Workflow

```text
AZURE_STATIC_WEB_APPS_API_TOKEN
VITE_API_BASE_URL
VITE_AUTH_CLIENT_ID
VITE_AUTH_AUTHORITY
VITE_AUTH_REDIRECT_URI
VITE_API_SCOPE
```

For a private demo without login, leave the auth-related `VITE_AUTH_*` values empty and keep backend `AUTH_REQUIRED=false`.

## Important

Rotate any key that was ever stored in a local `.env` before adding production secrets.
