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
  register as registerRequest,
} from "../api/auth";
import { clearReadResources } from "../hooks/readResourceStore";
import { clearCopyWorkspaceCache } from "../components/product/copyWorkspaceCache";

type AuthState = {
  checking: boolean;
  enabled: boolean;
  authenticated: boolean;
  username: string | null;
  authMode: "disabled" | "demo" | "user" | null;
  registrationEnabled: boolean;
  emailVerified: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  register: (email: string, password: string, workspaceName?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [checking, setChecking] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<"disabled" | "demo" | "user" | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [emailVerified, setEmailVerified] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applySession = useCallback(
    (session: {
      enabled: boolean;
      authenticated: boolean;
      username: string | null;
      registration_enabled?: boolean | null;
      auth_mode?: "disabled" | "demo" | "user" | null;
      email_verified?: boolean | null;
    }) => {
      clearReadResources();
      clearCopyWorkspaceCache();
      setEnabled(session.enabled);
      setAuthenticated(session.authenticated);
      setUsername(session.username);
      setAuthMode(session.auth_mode ?? null);
      setRegistrationEnabled(Boolean(session.registration_enabled));
      setEmailVerified(Boolean(session.email_verified));
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

  const refresh = useCallback(async () => {
    const session = await getAuthSession();
    applySession(session);
  }, [applySession]);

  useEffect(() => {
    const handleUnauthorized = () => {
      if (enabled) {
        clearReadResources();
        clearCopyWorkspaceCache();
        setAuthenticated(false);
        setUsername(null);
        setEmailVerified(false);
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

  const register = useCallback(
    async (email: string, password: string, workspaceName?: string) => {
      const session = await registerRequest(email, password, workspaceName);
      applySession(session);
    },
    [applySession],
  );

  const value = useMemo(
    () => ({
      checking,
      enabled,
      authenticated,
      username,
      authMode,
      registrationEnabled,
      emailVerified,
      error,
      login,
      register,
      logout,
      refresh,
    }),
    [
      checking,
      enabled,
      authenticated,
      username,
      authMode,
      registrationEnabled,
      emailVerified,
      error,
      login,
      register,
      logout,
      refresh,
    ],
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
