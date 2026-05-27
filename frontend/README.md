# Car Legalizer Frontend

React dashboard for the FastAPI DAV workflow.

## Run

```powershell
cd frontend
npm install
npm run dev
```

The backend defaults to `http://localhost:8000`. Copy `.env.example` to `.env` if you need a different API URL.

```powershell
VITE_API_BASE_URL=http://localhost:8000
```

React is installed as a project dependency by `npm install`; it does not need to be installed globally.
