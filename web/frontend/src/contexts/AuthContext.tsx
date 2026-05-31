import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "../services/api";
import type { User } from "../types";

const DEV_MODE = import.meta.env.VITE_DEV_MODE === "true";

// ---------- Context ----------
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (DEV_MODE) {
      setUser({
        id: "dev-user",
        email: "dev@agent.local",
        display_name: "Dev User",
      });
      setIsLoading(false);
      return;
    }

    // Production: Azure EasyAuth handles login at the infrastructure level.
    // By the time the app loads, the user is already authenticated.
    // Just call /api/auth/me to get user info from the EasyAuth headers.
    const init = async () => {
      try {
        const me = await api.getMe();
        setUser(me);
      } catch (err) {
        console.error("Failed to get user info:", err);
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, []);

  const logout = () => {
    setUser(null);
    // In EasyAuth, sign out by navigating to the Azure logout endpoint
    if (!DEV_MODE) {
      window.location.href = "/.auth/logout";
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
