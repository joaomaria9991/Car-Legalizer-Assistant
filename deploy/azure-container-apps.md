# Azure Container Apps Deploy

Recommended production shape:

- FastAPI backend on Azure Container Apps.
- React frontend on Azure Static Web Apps.
- Azure Blob Storage for process state/documents.
- Azure OpenAI for extraction and assistant reasoning.

## Backend Environment Variables

Configure these as Container App environment variables/secrets:

```text
AZURE_STORAGE_CONNECTION_STRING=secretref:azure-storage-connection-string
CONTAINER_NAME=car-legalization
AZURE_OPENAI_API_KEY=secretref:azure-openai-api-key
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-11-20
AUTH_REQUIRED=false
CORS_ORIGINS=https://<frontend>.azurestaticapps.net
```

For production login, switch `AUTH_REQUIRED=true` and add the Microsoft Entra variables documented in the main README.

## Suggested Azure Resources

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

## Local Container Build

```powershell
docker build -t car-legalizer-backend:local .
```

## Smoke Test

```powershell
Invoke-RestMethod https://<backend-url>/health
```

Then test the full product flow from the frontend:

1. Create process.
2. Upload documents.
3. Run classification/extraction.
4. Review with Assistant.
5. Inspect DAV Mirror.
