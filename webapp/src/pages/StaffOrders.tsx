import { useEffect, useState } from "react";
import { api, type Order } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";
import { useStaffScreen } from "../staffAccess";

export default function StaffOrdersPage() {
  const { allowed, gate } = useStaffScreen("Заказы staff");
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api
      .staffOrders()
      .then((data) => setOrders(data.orders))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (allowed) load();
  }, [allowed]);

  if (gate) return gate;
  if (loading) return <Layout title="Заказы staff"><Loading /></Layout>;

  return (
    <Layout title="Заказы staff">
      {error && <ErrorBox message={error} />}
      {!orders.length && !error && <Card>Заказов нет.</Card>}
      {orders.map((order) => (
        <Card key={order.id}>
          <p>#{order.id} · {order.product_name} × {order.qty}</p>
          <Button onClick={async () => { await api.staffOrderAction(order.id, "fulfill"); load(); }}>
            Выполнен
          </Button>
        </Card>
      ))}
    </Layout>
  );
}
