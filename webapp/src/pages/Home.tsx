import { Link } from "react-router-dom";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function HomePage() {
  const { me, loading, error } = useApp();

  if (loading) return <Layout><Loading /></Layout>;
  if (error) return <Layout><ErrorBox message={error} /></Layout>;

  if (me && !me.is_approved) {
    return (
      <Layout title="Lab21">
        <Card>
          <p>Добро пожаловать, {me.full_name}!</p>
          <p>
            Статус заявки: <strong>{me.join.state}</strong>
          </p>
          {me.join.state === "none" && (
            <Link to="/join" className="tile">
              Подать заявку
            </Link>
          )}
        </Card>
      </Layout>
    );
  }

  return (
    <Layout title={`Привет, ${me?.full_name ?? "гость"}`}>
      <div className="grid grid-2">
        <Link to="/shop" className="tile">Магазин</Link>
        <Link to="/order" className="tile">Заказ услуги</Link>
        <Link to="/jobs" className="tile">Мои заказы</Link>
        <Link to="/profile" className="tile">Профиль</Link>
        <Link to="/submit" className="tile">Публикации</Link>
        <Link to="/quests" className="tile">Квесты</Link>
        <Link to="/skills" className="tile">Кто умеет</Link>
        <Link to="/transfer" className="tile">Перевод</Link>
        <Link to="/history" className="tile">История</Link>
        <Link to="/faq" className="tile">FAQ</Link>
      </div>
      {me && (
        <Card>
          <p>Баланс: {me.balance} 🙏 · Уважение: {me.respect} ❇</p>
          <Button
            variant="secondary"
            onClick={async () => {
              const { api } = await import("../api");
              const result = await api.ritualBow();
              alert(result.message);
            }}
          >
            Приклониться
          </Button>
        </Card>
      )}
    </Layout>
  );
}
