import { useState } from "react";
import { api } from "../api";
import { Button, Card, ErrorBox, Layout } from "../components";

export default function TransferPage() {
  const [recipientId, setRecipientId] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("перевод");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  const submit = async () => {
    setError(null);
    try {
      await api.transfer(Number(recipientId), Number(amount), reason);
      setOk(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <Layout title="Перевод">
      {error && <ErrorBox message={error} />}
      {ok && <Card>Перевод выполнен</Card>}
      <Card>
        <label>Telegram ID получателя</label>
        <input value={recipientId} onChange={(e) => setRecipientId(e.target.value)} />
        <label>Сумма</label>
        <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" />
        <label>Причина</label>
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button onClick={submit}>Перевести</Button>
      </Card>
    </Layout>
  );
}
