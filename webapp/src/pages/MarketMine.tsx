import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type MarketListing } from "../api";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

const empty = {
  title: "",
  summary: "",
  description: "",
  category: "other",
  tags: "",
  currency: "grace" as "grace" | "rub",
  price: 1,
  kind: "regular" as "regular" | "collective",
  batch_threshold: 2,
  collection_ends_on: "",
};

export default function MarketMinePage() {
  const { me, refresh } = useApp();
  const [listings, setListings] = useState<MarketListing[]>([]);
  const [categories, setCategories] = useState<{ id: string; title: string }[]>([]);
  const [intro, setIntro] = useState("");
  const [form, setForm] = useState(empty);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.marketMeta(), api.marketMine()])
      .then(([meta, mine]) => {
        setCategories(meta.categories);
        setIntro(meta.intro);
        setListings(mine.listings);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Layout><Loading /></Layout>;

  const create = async () => {
    setError(null);
    try {
      const created = await api.marketCreate({
        title: form.title,
        summary: form.summary,
        description: form.description,
        category: form.category,
        tags: form.tags.split(",").map((part) => part.trim()).filter(Boolean),
        currency: form.currency,
        price: Number(form.price),
        kind: form.kind,
        batch_threshold: form.kind === "collective" ? Number(form.batch_threshold) : null,
        collection_ends_on: form.kind === "collective" ? form.collection_ends_on : null,
      });
      setListings((prev) => [created, ...prev]);
      setForm(empty);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  const upload = async (id: number, file: File | undefined) => {
    if (!file) return;
    try {
      const updated = await api.marketPhoto(id, file);
      setListings((prev) => prev.map((item) => (item.id === id ? updated : item)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <Layout title="Мои карточки">
      {error && <ErrorBox message={error} />}
      {me && !me.market_intro_seen && (
        <Card>
          <p>{intro}</p>
          <Button
            onClick={async () => {
              await api.marketIntro();
              await refresh();
            }}
          >
            Понятно
          </Button>
        </Card>
      )}
      <Card>
        <h3>Новая карточка</h3>
        <p>Количество появится, когда 21Lab примет изделия на склад.</p>
        <label>Тема</label>
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <label>Категория</label>
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
          {categories.map((item) => (
            <option key={item.id} value={item.id}>{item.title}</option>
          ))}
        </select>
        <label>Теги через запятую</label>
        <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        <label>Кратко</label>
        <input value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
        <label>Полное описание</label>
        <textarea
          rows={4}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <label>Тип</label>
        <select
          value={form.kind}
          onChange={(e) =>
            setForm({ ...form, kind: e.target.value as "regular" | "collective" })
          }
        >
          <option value="regular">В наличии, после сдачи на склад</option>
          <option value="collective">Коллективная заявка</option>
        </select>
        {form.kind === "collective" && (
          <>
            <label>Порог тиража</label>
            <input
              type="number"
              min={2}
              value={form.batch_threshold}
              onChange={(e) => setForm({ ...form, batch_threshold: Number(e.target.value) })}
            />
            <label>Набор до</label>
            <input
              type="date"
              value={form.collection_ends_on}
              onChange={(e) => setForm({ ...form, collection_ends_on: e.target.value })}
            />
          </>
        )}
        <label>Цена</label>
        <input
          type="number"
          min={1}
          value={form.price}
          onChange={(e) => setForm({ ...form, price: Number(e.target.value) })}
        />
        <label>Валюта</label>
        <select
          value={form.currency}
          onChange={(e) => setForm({ ...form, currency: e.target.value as "grace" | "rub" })}
        >
          <option value="grace">Благодать</option>
          <option value="rub" disabled={!me?.sales_mode}>Рубли (нужен режим продаж)</option>
        </select>
        <Button onClick={create}>Создать карточку изделия</Button>
      </Card>
      {listings.map((item) => (
        <Card key={item.id}>
          <h3>{item.title}</h3>
          <p>{item.price_label} · на складе {item.stock} · {item.status}</p>
          {item.kind === "collective" && (
            <p>Набор {item.pledge_count}/{item.batch_threshold}, фаза {item.phase}</p>
          )}
          <label>Фото</label>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={(e) => upload(item.id, e.target.files?.[0])}
          />
          <Link to={`/market/${item.id}`}>Открыть</Link>
        </Card>
      ))}
      <Link to="/market">К витрине</Link>
    </Layout>
  );
}
