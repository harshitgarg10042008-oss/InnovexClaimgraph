# ClaimGraph

ClaimGraph is a verifiable evidence compiler for MSME delayed-payment claims under the MSMED Act.
It ingests deal records, deterministically links and reconciles documents, and produces an audit-ready claim dossier.

For the architectural blueprint, roadmap, and specifications, see the [Master Plan](CLAIMGRAPH_MASTER_PLAN.md).

---

## Prerequisites

- **Docker** 24+ and **Docker Compose** v2+
- **Python** 3.11 (for local backend development)
- **Node.js** 20 LTS and **npm** 10+ (for local frontend development)

---

## Quick Start

1. **Clone the repository and set up environment variables:**
   ```bash
   cp .env.example .env
   ```

2. **Start all services with Docker Compose:**
   ```bash
   docker compose up --build
   ```

3. **Access the services:**
   - **Frontend (System Status):** [http://localhost:3000](http://localhost:3000)
   - **Backend API Root / Health:** [http://localhost:8000/health](http://localhost:8000/health)
   - **Interactive API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **PostgreSQL Database:** `localhost:5432` (db: `claimgraph`, user: `claimgraph`)

---

## Testing & Linting

### Backend

You can run linting and tests inside the running backend container or locally:

- **Inside Docker:**
  ```bash
  docker compose exec backend ruff check .
  docker compose exec backend pytest
  ```

- **Locally:**
  ```bash
  cd backend
  pip install -r requirements.txt -r requirements-dev.txt
  ruff check .
  pytest
  ```

### Frontend

Run linting, type-checking, and production build from the `frontend/` directory:

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

To format code with Prettier:
```bash
npm run format
```

To regenerate API TypeScript definitions from the running backend:
```bash
npm run gen:api
```
