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

3. **Seed synthetic cases and rate table data:**
   ```bash
   docker compose exec backend python -m app.seed
   ```

4. **Access the services:**
   - **Frontend (System Status):** [http://localhost:3000](http://localhost:3000)
   - **Backend API Root / Health:** [http://localhost:8000/health](http://localhost:8000/health)
   - **Interactive API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **PostgreSQL Database:** `localhost:5432` (db: `claimgraph`, user: `claimgraph`)

---

## Synthetic Cases

ClaimGraph includes four comprehensive, realistic synthetic test cases covering core commercial dispute patterns:
- **Case A (Main Demo):** Micro supplier with 460 vs 500 unit delivery gap, 1% TDS deduction, and progressive backorder addons.
- **Case B (Duplicates & Advance):** Duplicate billing detection and advance payments omitted from invoice face.
- **Case C (Ineligibility Gate):** Supplier whose Udyam registration postdates the contract date.
- **Case D (Messy Scan):** Camera photo of a stamped delivery challan with optical distortion and shortfall.

Detailed narratives, document schemas, and expected outputs are documented in [data/synthetic/README.md](data/synthetic/README.md).

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
