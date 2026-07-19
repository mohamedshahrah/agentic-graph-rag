import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";

import { ApiError, auth, type Me } from "../api";

interface AuthValue {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  setMe: (me: Me) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await auth.me());
    } catch (err) {
      // A 401 is the normal signed-out answer, not a failure worth surfacing.
      if (!(err instanceof ApiError && err.status === 401)) {
        console.warn("session check failed", err);
      }
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = async (email: string, password: string) => {
    setMe(await auth.login(email, password));
  };

  const signOut = async () => {
    try {
      await auth.logout();
    } finally {
      setMe(null);
    }
  };

  return (
    <AuthContext.Provider value={{ me, loading, refresh, signIn, signOut, setMe }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
    </div>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Loading />;
  // Remember where they were headed so sign-in can return them there.
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();

  if (loading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  // Send non-admins to chat rather than showing a locked page they can't use.
  if (me.role !== "admin") return <Navigate to="/chat" replace />;
  return <>{children}</>;
}
