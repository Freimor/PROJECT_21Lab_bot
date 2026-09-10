import { useEffect, useState } from "react";
import { api, type Product } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function ShopPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [qtyMap, setQtyMap] = useState<Record<number, number>>({});

  useEffect(() => {
    api
      .shopProducts()
      .then((data) => setProducts(data.products))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const buy = async (product: Product) => {
    const qty = qtyMap[product.id] ?? 1;
    try {
      await api.shopOrder(product.id, qty);
      alert(`Заказ «${product.name}» оформлен`);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Ошибка");
    }
  };

  if (loading) return <Layout><Loading /></Layout>;

  return (
    <Layout title="Магазин">
      {error && <ErrorBox message={error} />}
      {products.map((product) => (
        <Card key={product.id}>
          <h3>{product.name}</h3>
          <p>{product.description}</p>
          <p>{product.price} 🙏</p>
          {product.image_url && (
            <img src={product.image_url} alt={product.name} style={{ maxWidth: "100%" }} />
          )}
          <label>Количество</label>
          <input
            type="number"
            min={1}
            max={99}
            value={qtyMap[product.id] ?? 1}
            onChange={(e) =>
              setQtyMap({ ...qtyMap, [product.id]: Number(e.target.value) })
            }
          />
          <Button onClick={() => buy(product)} disabled={!product.available}>
            {product.available ? "Заказать" : "Недоступно"}
          </Button>
        </Card>
      ))}
      {!products.length && !error && <Card>Нет доступных товаров</Card>}
    </Layout>
  );
}
