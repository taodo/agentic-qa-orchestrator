# QA Sentinel — Agentic QA Orchestrator

QA Sentinel coordinates Project-owned QA Tasks through persisted evidence,
deterministic gates, reasoning agents and controlled code mutation. It includes
an explicitly composed Python application/API boundary and a React operator UI.

From this directory:

```shell
python -m pip install -e ".[test]"
python -m pytest
```

Backend startup requires trusted host runtime composition; installing the package
does not start a server or select a workspace. See docs/API.md and docs/PHASE_1.md
for composition, contract assumptions and current scope.

## Frontend development (Task 14)

```shell
cd frontend
npm install
npm run dev
```

Run `npm test -- --run` and `npm run build` for frontend checks. Vite proxies
`/api/v1` to `http://127.0.0.1:8000`; configure `VITE_API_PROXY_TARGET` for a
different separately composed backend host. There is no automatic backend
startup or production deployment. See [docs/FRONTEND.md](docs/FRONTEND.md).
