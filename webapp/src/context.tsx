import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Me } from "./api";

type AppContextValue = {
  me: Me | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getMe();
      setMe(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    window.Telegram?.WebApp?.ready();
    window.Telegram?.WebApp?.expand();
    void refresh();
  }, []);

  return (
    <AppContext.Provider value={{ me, loading, error, refresh }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}
