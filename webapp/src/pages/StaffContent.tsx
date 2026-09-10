import { useEffect, useState } from "react";
import { api, type Submission } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function StaffContentPage() {
  const [items, setItems] = useState<Submission[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.staffContentQueue().then((data) => setItems(data.items)).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  return (
    <Layout title="Модерация">
      {error && <ErrorBox message={error} />}
      {!items.length && !error && <Loading />}
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
