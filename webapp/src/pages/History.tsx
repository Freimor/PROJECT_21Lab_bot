import { useEffect, useState } from "react";
import { api, type HistoryEntry } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";

export default function HistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.history().then((data) => setEntries(data.entries)).catch((e) => setError(e.message));
  }, []);

  return (
    <Layout title="История">
      {error && <ErrorBox message={error} />}
      {!entries.length && !error && <Loading />}
      {entries.map((entry, idx) => (
        <Card key={`${entry.created_at}-${idx}`}>
          <div className="list-item">
            <span>{entry.reason}</span>
            <strong>{entry.delta > 0 ? "+" : ""}{entry.delta}</strong>
          </div>
          <small>{new Date(entry.created_at).toLocaleString("ru-RU")}</small>
        </Card>
      ))}
    </Layout>
  );
}
