import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type SkillCatalogItem } from "../api";
import { Button, Card, ErrorBox, Layout } from "../components";

export default function OrderServicePage() {
  const navigate = useNavigate();
  const [description, setDescription] = useState("");
  const [note, setNote] = useState("");
  const [price, setPrice] = useState(0);
  const [skills, setSkills] = useState<SkillCatalogItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.skillsCatalog().then((data) => setSkills(data.skills));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const submit = async () => {
    setError(null);
    try {
      await api.createJob({
        description,
        skill_ids: selected,
        price,
        assignee_note: note,
      });
      navigate("/jobs");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <Layout title="Заказ услуги">
      {error && <ErrorBox message={error} />}
      <Card>
        <label>Описание</label>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={5} />
        <label>Навыки</label>
        {skills.map((skill) => (
          <label key={skill.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={selected.includes(skill.id)}
              onChange={() => toggle(skill.id)}
            />
            {skill.title} ({skill.grace_price} 🙏)
          </label>
        ))}
        <label>Цена</label>
        <input type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} />
        <label>Примечание исполнителю</label>
        <input value={note} onChange={(e) => setNote(e.target.value)} />
        <Button onClick={submit}>Опубликовать заказ</Button>
      </Card>
    </Layout>
  );
}
