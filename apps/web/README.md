# web

React + TypeScript app (Vite, React Router, TanStack Query) that reaches every API endpoint the signed-in role may call. It uses the generated client in `packages/api-client`.

```bash
just web-dev      # from the repo root; needs `just api-dev` and `just db-up` running
just js-check     # typecheck + tests
just web-build    # production build in apps/web/dist
```

Sign in after `just seed` as `dave` / `teacher-pass` (teacher), `bob` / `builder` (student) or `alice` / `wonderland` (admin); each sees different navigation. The dev server proxies `/api` to `http://127.0.0.1:8000` (override with `API_URL`).

Source layout: `src/session.ts` (in-memory access token, single-flight refresh, retry on 401), `src/auth.tsx` (login, logout, role), `src/errors.ts` (FastAPI error bodies to messages), `src/roles.ts` (what each role sees), `src/components/RoleGate.tsx`, `src/pages/*` (screens), `src/test-utils.ts` (fetch stub).
