import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function ProfilePage() {
  const { me, refresh, loading, error } = useApp();
  const [bio, setBio] = useState("");
  const [skills, setSkills] = useState<{ id: string; title: string }[]>([]);
  const [owned, setOwned] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (me) {
      setBio(me.bio ?? "");
      setOwned(me.skill_ids);
    }
    api.skillsCatalog().then((data) => setSkills(data.skills)).catch(() => {});
  }, [me]);

  if (loading) return <Layout><Loading /></Layout>;
  if (error || !me) return <Layout><ErrorBox message={error ?? "Нет данных"} /></Layout>;

  const save = async () => {
    await api.patchMe({ bio });
    await refresh();
    setMsg("Сохранено");
  };

  const toggleNotify = async () => {
    await api.patchMe({ job_notify_enabled: !me.job_notify_enabled });
    await refresh();
  };

  const toggleSkill = async (skillId: string) => {
    if (owned.includes(skillId)) {
      await api.removeSkill(skillId);
    } else {
      await api.addSkill(skillId);
    }
    await refresh();
  };

  return (
    <Layout title="Профиль">
      {msg && <Card>{msg}</Card>}
      <Card>
        <p>{me.full_name}</p>
        <p>Ранг: {me.rank}</p>
        <p>{me.balance} 🙏 · {me.respect} ❇</p>
        <label>О себе</label>
        <textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={4} />
        <Button onClick={save}>Сохранить</Button>
        <Button variant="secondary" onClick={toggleNotify}>
          Уведомления о заказах: {me.job_notify_enabled ? "вкл" : "выкл"}
        </Button>
      </Card>
      <Card>
        <h3>Навыки</h3>
        {skills.map((skill) => (
          <div key={skill.id} className="list-item">
            <span>{skill.title}</span>
            <Button
              variant={owned.includes(skill.id) ? "danger" : "secondary"}
              onClick={() => toggleSkill(skill.id)}
            >
              {owned.includes(skill.id) ? "Убрать" : "Добавить"}
            </Button>
          </div>
        ))}
      </Card>
    </Layout>
  );
}
