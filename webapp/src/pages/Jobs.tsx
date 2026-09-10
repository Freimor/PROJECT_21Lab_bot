import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";

export default function JobsPage() {
  const [customer, setCustomer] = useState<Job[]>([]);
  const [assignee, setAssignee] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .myJobs()
      .then((data) => {
        setCustomer(data.as_customer);
        setAssignee(data.as_assignee);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Layout><Loading /></Layout>;

  const renderList = (items: Job[], title: string) => (
    <>
      <h2>{title}</h2>
      {items.map((job) => (
        <Card key={job.id}>
          <Link to={`/jobs/${job.id}`}>
            #{job.id} · {job.status} · {job.price} 🙏
          </Link>
          <p>{job.description.slice(0, 120)}</p>
        </Card>
      ))}
      {!items.length && <Card>Пусто</Card>}
    </>
  );

  return (
    <Layout title="Мои заказы">
      {error && <ErrorBox message={error} />}
      {renderList(customer, "Как заказчик")}
      {renderList(assignee, "Как исполнитель")}
    </Layout>
  );
}
