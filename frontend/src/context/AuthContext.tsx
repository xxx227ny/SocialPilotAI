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
  loggingOut: boolean;
  enabled: boolean;
  authenticated: boolean;
  username: string | null;
  authMode: "disabled" | "demo" | "user" | null;
  registrationEnabled: boolean;
  emailVerified: boolean;
  emailDeliveryAvailable: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  register: (email: string, password: string, workspaceName?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);
const LOGOUT_PENDING_KEY = "socialpilot:logout-pending";

export function AuthProvider({ children }: PropsWithChildren) {
  const [checking, setChecking] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<"disabled" | "demo" | "user" | null>(null);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [emailVerified, setEmailVerified] = useState(false);
  const [emailDeliveryAvailable, setEmailDeliveryAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyLocalLogout = useCallback((nextError: string | null = null) => {
    clearReadResources();
    clearCopyWorkspaceCache();
    setAuthenticated(false);
    setUsername(null);
    setEmailVerified(false);
    setError(nextError);
  }, []);

  const applySession = useCallback(
    (session: {
      enabled: boolean;
      authenticated: boolean;
      username: string | null;
      registration_enabled?: boolean | null;
      auth_mode?: "disabled" | "demo" | "user" | null;
      email_verified?: boolean | null;
      email_delivery_available?: boolean | null;
    }) => {
      clearReadResources();
      clearCopyWorkspaceCache();
      setEnabled(session.enabled);
      setAuthenticated(session.authenticated);
      setUsername(session.username);
      setAuthMode(session.auth_mode ?? null);
      setRegistrationEnabled(Boolean(session.registration_enabled));
      setEmailVerified(Boolean(session.email_verified));
      setEmailDeliveryAvailable(Boolean(session.email_delivery_available));
      setError(null);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    const logoutWasPending = window.sessionStorage.getItem(LOGOUT_PENDING_KEY) === "1";
    const request = logoutWasPending ? logoutRequest() : getAuthSession();
    request
      .then((session) => {
        if (active) {
          if (logoutWasPending) window.sessionStorage.removeItem(LOGOUT_PENDING_KEY);
          applySession(session);
        }
      })
      .catch(() => {
        if (active) {
          if (logoutWasPending) {
            applyLocalLogout("已退出当前页面；服务器退出请求尚未确认，刷新时将继续完成。");
          } else {
            setError("暂时无法连接登录服务，请检查网络、代理或 VPN 后重新连接。");
            setAuthenticated(false);
          }
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [applyLocalLogout, applySession]);

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
      window.sessionStorage.removeItem(LOGOUT_PENDING_KEY);
      applySession(session);
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    window.sessionStorage.setItem(LOGOUT_PENDING_KEY, "1");
    applyLocalLogout();
    try {
      const session = await logoutRequest();
      window.sessionStorage.removeItem(LOGOUT_PENDING_KEY);
      applySession(session);
    } catch {
      applyLocalLogout("已退出当前页面；服务器退出请求尚未确认，刷新时将继续完成。");
    } finally {
      setLoggingOut(false);
    }
  }, [applyLocalLogout, applySession, loggingOut]);

  const register = useCallback(
    async (email: string, password: string, workspaceName?: string) => {
      const session = await registerRequest(email, password, workspaceName);
      window.sessionStorage.removeItem(LOGOUT_PENDING_KEY);
      applySession(session);
    },
    [applySession],
  );

  const value = useMemo(
    () => ({
      checking,
      loggingOut,
      enabled,
      authenticated,
      username,
      authMode,
      registrationEnabled,
      emailVerified,
      emailDeliveryAvailable,
      error,
      login,
      register,
      logout,
      refresh,
    }),
    [
      checking,
      loggingOut,
      enabled,
      authenticated,
      username,
      authMode,
      registrationEnabled,
      emailVerified,
      emailDeliveryAvailable,
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
