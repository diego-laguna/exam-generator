# web

React + TypeScript app for teachers (Vite, React Router, TanStack Query). It uses the generated client in `packages/api-client`.

```bash
just web-dev      # from the repo root; needs `just api-dev` and `just db-up` running
just js-check     # typecheck + tests
just web-build    # production build in apps/web/dist
```

Sign in with a teacher account (`dave` / `teacher-pass` after `just seed`). The dev server proxies `/api` to `http://127.0.0.1:8000` (override with `API_URL`).

Source layout: `src/session.ts` (in-memory access token, single-flight refresh, retry on 401), `src/auth.tsx` (login, logout, role), `src/errors.ts` (FastAPI error bodies to messages), `src/pages/*` (screens), `src/test-utils.ts` (fetch stub).
