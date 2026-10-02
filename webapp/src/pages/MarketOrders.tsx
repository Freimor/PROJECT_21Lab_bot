import { useEffect, useState } from "react";
import { api, type MarketDeal } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

function DealCard({
  deal,
  onChange,
}: {
  deal: MarketDeal;
  onChange: () => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <Card>
      <h3>{deal.title}</h3>
      <p>{deal.quantity} шт. · {deal.price_label}</p>
      <p>Статус: {deal.status}</p>
      {deal.qr_token && <p className="pickup-code">{deal.qr_token}</p>}
      {deal.qr_svg && (
        <div className="qr-wrap" dangerouslySetInnerHTML={{ __html: deal.qr_svg }} />
      )}
      {deal.status === "reserved" && (
        <Button
          variant="secondary"
          onClick={async () => {
            try {
              await api.marketRefuse(deal.id);
              onChange();
            } catch (e) {
              setError(e instanceof Error ? e.message : "Ошибка");
            }
          }}
        >
          Отказаться до выдачи
        </Button>
      )}
      {deal.status === "issued" && (
        <>
          <label>Спор</label>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} />
          <Button
            variant="danger"
            onClick={async () => {
              try {
                await api.marketDispute(deal.id, text);
                onChange();
              } catch (e) {
                setError(e instanceof Error ? e.message : "Ошибка");
              }
            }}
          >
            Открыть спор
          </Button>
        </>
      )}
      {error && <ErrorBox message={error} />}
    </Card>
  );
}

export default function MarketOrdersPage() {
  const [purchases, setPurchases] = useState<MarketDeal[]>([]);
  const [sales, setSales] = useState<MarketDeal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api
      .marketDeals()
      .then((data) => {
        setPurchases(data.purchases);
        setSales(data.sales);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading) return <Layout><Loading /></Layout>;

  return (
    <Layout title="Заказы ярмарки">
      {error && <ErrorBox message={error} />}
      <h2>Мои покупки</h2>
      {purchases.map((deal) => (
        <DealCard key={deal.id} deal={deal} onChange={load} />
      ))}
      {purchases.length === 0 && <Card>Покупок нет.</Card>}
      <h2>Мои продажи</h2>
      {sales.map((deal) => (
        <Card key={deal.id}>
          <h3>{deal.title}</h3>
          <p>{deal.quantity} шт. · {deal.price_label} · {deal.status}</p>
        </Card>
      ))}
    </Layout>
  );
}
