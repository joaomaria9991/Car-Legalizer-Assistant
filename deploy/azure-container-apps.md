# Azure Deploy Guide

This project deploys as:

- Backend: FastAPI container on Azure Container Apps.
- Frontend: Vite/React on Azure Static Web Apps.
- Storage/OpenAI: existing Azure Blob Storage and Azure OpenAI resources.

## 0. Rotate Secrets First

The local `.env` has real Azure keys. Treat them as compromised before any public deploy:

- Regenerate the Storage Account key or move to a new connection string.
- Regenerate the Azure OpenAI key.
- Store new values only in Azure Container App secrets / GitHub Actions secrets.

## 1. Azure Resources

```powershell
$RESOURCE_GROUP="rg-car-legalizer-demo"
$LOCATION="westeurope"
$ACR_NAME="carlegalizeracr"
$ACA_ENV="car-legalizer-env"
$BACKEND_APP="car-legalizer-api"

az group create --name $RESOURCE_GROUP --location $LOCATION
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true
az containerapp env create --resource-group $RESOURCE_GROUP --name $ACA_ENV --location $LOCATION
```

Create the first backend Container App with a placeholder image after the first image is pushed, or deploy from GitHub Actions once `CONTAINER_APP_NAME` exists.

## 2. Backend Container App Settings

Set secrets:

```powershell
az containerapp secret set `
  --resource-group $RESOURCE_GROUP `
  --name $BACKEND_APP `
  --secrets `
    azure-storage-connection-string="<rotated-storage-connection-string>" `
    azure-openai-api-key="<rotated-openai-key>"
```

Set runtime environment variables:

```powershell
az containerapp update `
  --resource-group $RESOURCE_GROUP `
  --name $BACKEND_APP `
  --min-replicas 1 `
  --cpu 1.0 `
  --memory 2Gi `
  --set-env-vars `
    AZURE_STORAGE_CONNECTION_STRING=secretref:azure-storage-connection-string `
    CONTAINER_NAME="car-legalization" `
    AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key `
    AZURE_OPENAI_ENDPOINT="https://<your-openai-resource>.openai.azure.com/" `
    AZURE_OPENAI_DEPLOYMENT="gpt-4o" `
    AZURE_OPENAI_API_VERSION="2024-11-20" `
    AUTH_REQUIRED="false" `
    CORS_ORIGINS="https://<your-static-web-app>.azurestaticapps.net"
```

Keep `AUTH_REQUIRED=false` for the private demo phase. When auth is enabled later, add the `AZURE_AUTH_*` variables and set it to `true`.

## 3. GitHub Secrets

Backend workflow secrets:

- `AZURE_CREDENTIALS`: JSON output from an Azure service principal.
- `AZURE_RESOURCE_GROUP`: `rg-car-legalizer-demo`
- `ACR_NAME`: ACR resource name, for example `carlegalizeracr`
- `ACR_LOGIN_SERVER`: for example `carlegalizeracr.azurecr.io`
- `CONTAINER_APP_NAME`: backend Container App name

Frontend workflow secrets:

- `AZURE_STATIC_WEB_APPS_API_TOKEN`
- `VITE_API_BASE_URL`: backend Container App URL, for example `https://car-legalizer-api.<region>.azurecontainerapps.io`
- `VITE_AUTH_CLIENT_ID`: leave empty for demo without login
- `VITE_AUTH_AUTHORITY`: leave empty or `https://login.microsoftonline.com/common`
- `VITE_AUTH_REDIRECT_URI`: leave empty until login is enabled
- `VITE_API_SCOPE`: leave empty until login is enabled

## 4. Local Validation

```powershell
venv\Scripts\python.exe -m unittest discover -s app\tests -p "test*.py"
venv\Scripts\python.exe -m compileall -q app
docker build -t car-legalizer-backend:local .

cd frontend
npm install
npm run build
```

## 5. Smoke Test

After deploy:

```powershell
Invoke-RestMethod https://<backend-url>/health
```

Then open the Static Web App and test:

1. Create a new process.
2. Upload PDF/image pages.
3. Confirm classification and extract progress.
4. Open Assistant and DAV Mirror.
5. Confirm documents can be previewed/downloaded.

## 6. Enable Login Later

When moving from private demo to production:

- Configure Microsoft Entra app registration and API scope.
- Add frontend `VITE_AUTH_*` secrets.
- Add backend `AZURE_AUTH_AUTHORITY`, `AZURE_API_AUDIENCE`, `AZURE_ALLOWED_CLIENT_IDS`, `AZURE_REQUIRED_SCOPE`.
- Set `AUTH_REQUIRED=true`.
- Update `CORS_ORIGINS` to only the production Static Web App URL.
