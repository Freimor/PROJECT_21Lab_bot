import { useEffect, useState } from "react";
import { api, type Submission } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";
import { useStaffScreen } from "../staffAccess";

export default function StaffContentPage() {
  const { allowed, gate } = useStaffScreen("Модерация");
  const [items, setItems] = useState<Submission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api
      .staffContentQueue()
      .then((data) => setItems(data.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (allowed) load();
  }, [allowed]);

  if (gate) return gate;
  if (loading) return <Layout title="Модерация"><Loading /></Layout>;

  return (
    <Layout title="Модерация">
      {error && <ErrorBox message={error} />}
      {!items.length && !error && <Card>Очередь пуста.</Card>}
      {items.map((item) => (
        <Card key={item.id}>
          <p>#{item.id} · {item.kind}</p>
          <p>{item.source_text.slice(0, 200)}</p>
          <Button onClick={async () => { await api.staffContentAction(item.id, "approve"); load(); }}>
            Одобрить
          </Button>
          <Button variant="danger" onClick={async () => { await api.staffContentAction(item.id, "reject"); load(); }}>
            Отклонить
          </Button>
        </Card>
      ))}
    </Layout>
  );
}
