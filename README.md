# QA Sentinel — Agentic QA Orchestrator

QA Sentinel coordinates Project-owned QA Tasks through persisted evidence,
deterministic gates, reasoning agents and controlled code mutation. It includes
an explicitly composed Python application/API boundary and a React operator UI.

From this directory:

```shell
python -m pip install -e ".[test]"
python -m pytest
```

Installing the package does not start a server or select a workspace.

## First-run offline demo (Task 16)

```shell
python -m pip install -e ".[test]"
cd frontend
npm ci
npm run build
cd ..
qa-sentinel serve --demo
```

Open http://127.0.0.1:8000. Select Demo Calculator, create a division Task and Run.
Demo agent/test evidence is synthetic: no API key, network, source writes or real
test process is needed. Default file-backed state is `~/.qa-sentinel/demo/`.
The host binds only to loopback and has no authentication. Real local mode can
mutate explicitly configured trusted workspaces; see [docs/HOSTING.md](docs/HOSTING.md)
for JSON configuration, boundaries and troubleshooting.

## Protected demo preview (Task 17)

The Docker/Render deployment path runs only the deterministic Demo Calculator,
behind an environment-only HTTP Basic gate. Real local execution stays loopback-only.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for private-repository setup, required
dashboard secrets, ephemeral SQLite state and the local container smoke test.
Deployment awaits review and user approval; no preview URL has been provisioned.

## Frontend development (Task 14)

```shell
cd frontend
npm install
npm run dev
```

Run `npm test -- --run` and `npm run build` for frontend checks. Vite proxies
`/api/v1` to `http://127.0.0.1:8000`; configure `VITE_API_PROXY_TARGET` for a
different local backend host. `qa-sentinel serve` serves built assets directly;
Vite development remains separate. See [docs/FRONTEND.md](docs/FRONTEND.md).
