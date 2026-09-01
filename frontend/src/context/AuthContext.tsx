import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getAuthSession,
  login as loginRequest,
  logout as logoutRequest,
} from "../api/auth";
import { clearReadResources } from "../hooks/readResourceStore";
import { clearCopyWorkspaceCache } from "../components/product/copyWorkspaceCache";

type AuthState = {
  checking: boolean;
  enabled: boolean;
  authenticated: boolean;
  username: string | null;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [checking, setChecking] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applySession = useCallback(
    (session: { enabled: boolean; authenticated: boolean; username: string | null }) => {
      clearReadResources();
      clearCopyWorkspaceCache();
      setEnabled(session.enabled);
      setAuthenticated(session.authenticated);
      setUsername(session.username);
      setError(null);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    getAuthSession()
      .then((session) => {
        if (active) applySession(session);
      })
      .catch(() => {
        if (active) {
          setError("暂时无法连接登录服务，请确认本机服务已启动。");
          setAuthenticated(false);
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [applySession]);

  useEffect(() => {
    const handleUnauthorized = () => {
      if (enabled) {
        clearReadResources();
        clearCopyWorkspaceCache();
        setAuthenticated(false);
        setUsername(null);
      }
    };
    window.addEventListener("socialpilot:unauthorized", handleUnauthorized);
    return () => {
      window.removeEventListener("socialpilot:unauthorized", handleUnauthorized);
    };
  }, [enabled]);

  const login = useCallback(
    async (nextUsername: string, password: string) => {
      const session = await loginRequest(nextUsername, password);
      applySession(session);
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    const session = await logoutRequest();
    applySession(session);
  }, [applySession]);

  const value = useMemo(
    () => ({
      checking,
      enabled,
      authenticated,
      username,
      error,
      login,
      logout,
    }),
    [checking, enabled, authenticated, username, error, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
