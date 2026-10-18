import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, toApiError } from "./errors";
import { api, onSessionExpired, refreshAccessToken, roleFromToken, setAccessToken } from "./session";

type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; role: string | null };

interface AuthContextValue {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let active = true;
    void refreshAccessToken().then((token) => {
      if (!active) return;
      setState(token ? { status: "authenticated", role: roleFromToken(token) } : { status: "anonymous" });
    });
    const unsubscribe = onSessionExpired(() => setState({ status: "anonymous" }));
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { data, error, response } = await api.POST("/api/v1/auth/login", {
      body: { username, password, scope: "" },
      // The login endpoint takes a form (OAuth2 password flow), not JSON.
      bodySerializer: (body) => new URLSearchParams(body as Record<string, string>),
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    if (error !== undefined || !data) {
      const apiError = toApiError(response.status, error);
      throw response.status === 401 ? new ApiError("Incorrect username or password", 401) : apiError;
    }
    setAccessToken(data.access_token);
    setState({ status: "authenticated", role: roleFromToken(data.access_token) });
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      setAccessToken(null);
      setState({ status: "anonymous" });
    }
  }, []);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
