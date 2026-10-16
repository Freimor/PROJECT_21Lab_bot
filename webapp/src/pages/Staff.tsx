import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StaffDashboard } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";
import { useStaffScreen } from "../staffAccess";

export default function StaffPage() {
  const { allowed, gate } = useStaffScreen("Staff");
  const [dash, setDash] = useState<StaffDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!allowed) return;
    api.staffDashboard().then(setDash).catch((e) => setError(e.message));
  }, [allowed]);

  if (gate) return gate;
  if (!dash && !error) return <Layout><Loading /></Layout>;

  return (
    <Layout title="Staff">
      {error && <ErrorBox message={error} />}
      {dash && (
        <>
          <Card>
            <p>Заявки: {dash.pending_applications}</p>
            <p>Модерация: {dash.moderation_queue}</p>
            <p>Заказы: {dash.pending_orders}</p>
          </Card>
          <div className="grid">
            <Link to="/staff/content" className="tile">Модерация</Link>
            <Link to="/staff/orders" className="tile">Заказы</Link>
            <Link to="/staff/people" className="tile">Заявки</Link>
            <Link to="/staff/settings" className="tile">Настройки</Link>
          </div>
        </>
      )}
    </Layout>
  );
}
