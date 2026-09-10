import { useEffect, useState } from "react";
import { api, type Submission } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function SubmitPage() {
  const [items, setItems] = useState<Submission[]>([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.mySubmissions().then((data) => setItems(data.items)).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  return (
    <Layout title="Публикации">
      {error && <ErrorBox message={error} />}
      <Card>
        <label>Текст поста</label>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} />
        <Button
          onClick={async () => {
            await api.submitPost("story", text);
            setText("");
            load();
          }}
        >
          Отправить пост
        </Button>
      </Card>
      <Card>
        <label>Мем (фото/GIF)</label>
        <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Button
          onClick={async () => {
            if (!file) return;
            await api.submitMeme(file, text);
            setFile(null);
            load();
          }}
        >
          Отправить мем
        </Button>
      </Card>
      <h2>Мои материалы</h2>
      {!items.length && <Loading />}
      {items.map((item) => (
        <Card key={item.id}>
          #{item.id} · {item.kind} · {item.status}
        </Card>
      ))}
    </Layout>
  );
}
