import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function StaffPeoplePage() {
  const [apps, setApps] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api
      .staffApplications()
      .then((data) => setApps(data.applications))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading) return <Layout title="Заявки"><Loading /></Layout>;

  return (
    <Layout title="Заявки">
      {error && <ErrorBox message={error} />}
      {!apps.length && !error && <Card>Заявок нет.</Card>}
      {apps.map((app) => (
        <Card key={String(app.id)}>
          <p>#{String(app.id)} · {String(app.kind)} · {String(app.status)}</p>
          <Button onClick={async () => { await api.staffApplicationAction(Number(app.id), "approve"); load(); }}>
            Одобрить
          </Button>
          <Button variant="danger" onClick={async () => { await api.staffApplicationAction(Number(app.id), "reject"); load(); }}>
            Отклонить
          </Button>
        </Card>
      ))}
    </Layout>
  );
}
