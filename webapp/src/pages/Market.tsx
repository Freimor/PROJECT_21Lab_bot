import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type MarketListing } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";

export default function MarketPage() {
  const [listings, setListings] = useState<MarketListing[]>([]);
  const [categories, setCategories] = useState<{ id: string; title: string }[]>([]);
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.marketMeta().then((meta) => setCategories(meta.categories)).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    api
      .marketListings(category || undefined)
      .then((data) => setListings(data.listings))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [category]);

  if (loading && listings.length === 0) return <Layout><Loading /></Layout>;

  return (
    <Layout title="Маркет">
      {error && <ErrorBox message={error} />}
      <div className="grid grid-2">
        <Link to="/market/mine" className="tile">Мои карточки</Link>
        <Link to="/market/orders" className="tile">Мои заказы</Link>
      </div>
      <label>Категория</label>
      <select value={category} onChange={(e) => setCategory(e.target.value)}>
        <option value="">Все</option>
        {categories.map((item) => (
          <option key={item.id} value={item.id}>{item.title}</option>
        ))}
      </select>
      {listings.map((item) => (
        <Link key={item.id} to={`/market/${item.id}`}>
          <Card>
            {item.photos[0] && <img className="market-photo" src={item.photos[0]} alt="" />}
            <h3>{item.title}</h3>
            <p>{item.summary}</p>
            <p>{item.price_label} · {item.author}</p>
            {item.kind === "collective" ? (
              <p>Набор {item.pledge_count}/{item.batch_threshold} до {item.collection_ends_on}</p>
            ) : (
              <p>На складе: {item.stock}</p>
            )}
          </Card>
        </Link>
      ))}
      {listings.length === 0 && !error && <Card>Пока пусто.</Card>}
    </Layout>
  );
}
