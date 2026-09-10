import { useEffect, useState } from "react";
import { api, type Order } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function StaffOrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.staffOrders().then((data) => setOrders(data.orders)).catch((e) => setError(e.message));
  };

  useEffect(load, []);

  return (
    <Layout title="Заказы staff">
      {error && <ErrorBox message={error} />}
      {!orders.length && !error && <Loading />}
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
