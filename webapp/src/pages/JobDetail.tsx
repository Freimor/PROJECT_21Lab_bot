import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Job } from "../api";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function JobDetailPage() {
  const { id } = useParams();
  const { me } = useApp();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!id) return;
    api.getJob(Number(id)).then(setJob).catch((e) => setError(e.message));
  };

  useEffect(load, [id]);

  if (!job && !error) return <Layout><Loading /></Layout>;
  if (error || !job || !me) return <Layout><ErrorBox message={error ?? "Не найден"} /></Layout>;

  const isCustomer = job.customer_id === me.telegram_id;
  const isAssignee = job.assignee_id === me.telegram_id;

  return (
    <Layout title={`Заказ #${job.id}`}>
      <Card>
        <p className="badge">{job.status}</p>
        <p>{job.description}</p>
        <p>{job.price} 🙏</p>
        {job.result_text && <p>Отчёт: {job.result_text}</p>}
      </Card>
      {job.status === "open" && !isCustomer && (
        <Button
          onClick={async () => {
            await api.claimJob(job.id);
            load();
          }}
        >
          Взять заказ
        </Button>
      )}
      {job.status === "claimed" && isAssignee && (
        <>
          <textarea
            value={report}
            onChange={(e) => setReport(e.target.value)}
            placeholder="Отчёт о выполнении"
            rows={5}
          />
          <Button
            onClick={async () => {
              await api.submitJobResult(job.id, report);
              navigate("/jobs");
            }}
          >
            Сдать работу
          </Button>
        </>
      )}
      {job.status === "review" && isCustomer && (
        <>
          <Button
            onClick={async () => {
              await api.reviewJob(job.id, true);
              navigate("/jobs");
            }}
          >
            Подтвердить
          </Button>
          <Button
            variant="danger"
            onClick={async () => {
              await api.reviewJob(job.id, false);
              navigate("/jobs");
            }}
          >
            Не подтверждать
          </Button>
        </>
      )}
    </Layout>
  );
}
