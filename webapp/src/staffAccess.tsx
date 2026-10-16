import type { ReactElement } from "react";
import { ErrorBox, Layout, Loading } from "./components";
import { useApp } from "./context";

export function useStaffScreen(title: string): {
  allowed: boolean;
  gate: ReactElement | null;
} {
  const { me, loading } = useApp();
  if (loading) {
    return { allowed: false, gate: <Layout title={title}><Loading /></Layout> };
  }
  if (!me?.is_staff) {
    return {
      allowed: false,
      gate: <Layout title={title}><ErrorBox message="Нет доступа" /></Layout>,
    };
  }
  return { allowed: true, gate: null };
}
