# Car-Legalizer-Assiatnt
My App meant to help legalizing cars in Portugal following AT (Autoridade Tributarias's) rules and helping you to navigate all the legal forms

uvicorn app.main:app --reload --port 8000

python -m app.test_manual

## Frontend

The React dashboard lives in `frontend/`.

```powershell
cd frontend
npm install
npm run dev
```

It expects the API at `http://localhost:8000` by default. Copy `frontend/.env.example` to `frontend/.env` to change `VITE_API_BASE_URL`.

## Azure Deploy

The deployment target is:

- FastAPI backend on Azure Container Apps.
- React frontend on Azure Static Web Apps.
- Blob Storage and Azure OpenAI configured through Azure/GitHub secrets.

Start with [`deploy/azure-container-apps.md`](deploy/azure-container-apps.md), then add the GitHub secrets listed in [`deploy/github-actions-secrets.md`](deploy/github-actions-secrets.md).

Before deploying, rotate any keys that were used in a local `.env` file and keep production values out of git.
