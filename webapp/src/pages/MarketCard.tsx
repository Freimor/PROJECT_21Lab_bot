import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type MarketListing } from "../api";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function MarketCardPage() {
  const { id } = useParams();
  const { me } = useApp();
  const [item, setItem] = useState<MarketListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qty, setQty] = useState(1);
  const [handover, setHandover] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!id) return;
    api.marketListing(Number(id)).then(setItem).catch((e) => setError(e.message));
  };

  useEffect(load, [id]);

  if (!item && !error) return <Layout><Loading /></Layout>;
  if (error && !item) return <Layout><ErrorBox message={error} /></Layout>;
  if (!item) return null;

  const mine = me && item.seller_id === me.telegram_id;
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout title={item.title}>
      {error && <ErrorBox message={error} />}
      <Card>
        {item.photos.map((src) => (
          <img key={src} className="market-photo" src={src} alt="" />
        ))}
        <p>{item.category_label} · {item.author}</p>
        <p>{item.summary}</p>
        <p>{item.description}</p>
        {item.tags.length > 0 && <p>{item.tags.join(", ")}</p>}
        <p>{item.price_label}</p>
        {item.kind === "collective" ? (
          <p>
            Набор {item.pledge_count}/{item.batch_threshold}
            {item.collection_ends_on ? ` до ${item.collection_ends_on}` : ""}
            {item.handover_on ? `. Привоз ${item.handover_on}` : ""}
          </p>
        ) : (
          <p>На складе: {item.stock}. Можно забрать: {item.available}</p>
        )}
        {item.buyable && !mine && (
          <>
            <label>Сколько штук</label>
            <input
              type="number"
              min={1}
              max={item.available}
              value={qty}
              onChange={(e) => setQty(Number(e.target.value))}
            />
            <Button disabled={busy} onClick={() => run(() => api.marketBuy(item.id, qty))}>
              Купить
            </Button>
          </>
        )}
        {item.joinable && !mine && !item.joined && (
          <Button disabled={busy} onClick={() => run(() => api.marketJoin(item.id))}>
            Присоединиться к коллективной заявке
          </Button>
        )}
        {item.joined && item.joinable && (
          <Button variant="secondary" disabled={busy} onClick={() => run(() => api.marketLeave(item.id))}>
            Выйти из набора
          </Button>
        )}
        {mine && item.kind === "collective" && item.phase === "ready" && (
          <>
            <label>Дата, когда привезёшь партию</label>
            <input type="date" value={handover} onChange={(e) => setHandover(e.target.value)} />
            <Button
              disabled={busy || !handover}
              onClick={() => run(() => api.marketHandover(item.id, handover))}
            >
              Сохранить дату привоза
            </Button>
          </>
        )}
        <Link to="/market">К витрине</Link>
      </Card>
    </Layout>
  );
}
