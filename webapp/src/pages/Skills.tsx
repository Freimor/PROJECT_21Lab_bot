import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";

export default function SkillsPage() {
  const [skills, setSkills] = useState<{ id: string; title: string }[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [detail, setDetail] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.skillsBoard().then((data) => setSkills(data.skills)).catch((e) => setError(e.message));
  }, []);

  const open = async (id: string) => {
    setActive(id);
    const data = await api.skillBoardDetail(id);
    setDetail(data.text);
  };

  return (
    <Layout title="Кто умеет">
      {error && <ErrorBox message={error} />}
      {!skills.length && !error && <Loading />}
      {skills.map((skill) => (
        <Card key={skill.id}>
          <button type="button" className="btn btn-secondary" onClick={() => open(skill.id)}>
            {skill.title}
          </button>
        </Card>
      ))}
      {active && (
        <Card>
          <pre style={{ whiteSpace: "pre-wrap" }}>{detail}</pre>
        </Card>
      )}
    </Layout>
  );
}
