import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout } from "../components";

export default function JoinPage() {
  const { refresh } = useApp();
  const navigate = useNavigate();
  const [kind, setKind] = useState<"community" | "staff">("community");
  const [bio, setBio] = useState("");
  const [skillsText, setSkillsText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.submitJoin({
        kind,
        bio: kind === "community" ? bio : undefined,
        skills_text: kind === "community" ? skillsText : undefined,
      });
      await refresh();
      navigate("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout title="Заявка">
      {error && <ErrorBox message={error} />}
      <Card>
        <label>Тип</label>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as "community" | "staff")}
        >
          <option value="community">Послушник</option>
          <option value="staff">Сотрудник</option>
        </select>
        {kind === "community" && (
          <>
            <label>О себе</label>
            <textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={4} />
            <label>Навыки (текстом)</label>
            <textarea
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
              rows={4}
            />
          </>
        )}
        <Button onClick={submit} disabled={loading}>
          Отправить заявку
        </Button>
      </Card>
    </Layout>
  );
}
