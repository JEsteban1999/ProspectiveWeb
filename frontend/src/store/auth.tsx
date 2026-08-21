/* AuthContext — JWT + current user, persisted in localStorage. */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "../api/client";
import type { UserInfo } from "../api/types";

interface AuthState {
  user: UserInfo | null;
  ready: boolean;
  /** Set when the session ended on its own (expired token), so the login screen
   *  can say why instead of looking like a random logout. */
  expiredNotice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  clearExpiredNotice: () => void;
}

const AuthContext = createContext<AuthState>({
  user: null,
  ready: false,
  expiredNotice: null,
  login: async () => {},
  logout: () => {},
  clearExpiredNotice: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [ready, setReady] = useState(false);
  const [expiredNotice, setExpiredNotice] = useState<string | null>(null);

  // Any 401 from any panel ends the session here, once. Without this the token
  // could expire mid-study and every panel would just show its own error while
  // the user kept clicking.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser((current) => {
        if (current) setExpiredNotice("Tu sesión ha caducado. Vuelve a iniciar sesión.");
        return null;
      });
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  // Restore session from a stored token on first load.
  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    setToken(res.access_token);
    setUser(res.user);
    setExpiredNotice(null);
  }, []);

  const logout = useCallback(() => {
    // Clear the cookie server-side too; dropping the local token alone would
    // leave the browser able to fetch imaging from /data and /api/slice.
    void api.logout().catch(() => { /* best effort: the token may already be dead */ });
    setToken(null);
    setUser(null);
    setExpiredNotice(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, ready, expiredNotice, login, logout, clearExpiredNotice: () => setExpiredNotice(null) }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
