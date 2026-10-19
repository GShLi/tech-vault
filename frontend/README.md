# TechVault Frontend

Vue 3 + Vite + TypeScript frontend for the TechVault API.

## Current scope

- Login and self-service password change
- Administrator-managed account creation; external registration is disabled
- Team selection and team creation
- Knowledge-base list, create, edit and archive
- Role-aware controls (`leader` can manage, `member`/`viewer` are read-only)
- Cursor pagination and API error envelopes
- Chat workspace shell, pending the document ingestion and chat APIs

## Local development

The repository environment has Node v22 under nvm. Load it into `PATH`:

```bash
export PATH="$HOME/.nvm/versions/node/v22.15.0/bin:$PATH"
npm install
npm run dev
```

The Vite dev server runs at `http://127.0.0.1:5173` and proxies `/api` to
`http://127.0.0.1:8000`. Start the backend with:

```bash
cd ..
TECHVAULT_ENVIRONMENT=development .venv/bin/uvicorn backend.app.main:create_app --factory --reload
```

Initial administrator credentials are `admin@techvault.local` /
`ChangeMe-123!`. Change the password from Settings after first login.

## Verification

```bash
npm test
npm run build
npm run integration
```

`npm run integration` uses the system Google Chrome through `playwright-core`
and requires both servers to be running. It registers a fresh user, creates a
team and knowledge base, reloads the page, and writes a screenshot to
`artifacts/frontend-integration.png`.

