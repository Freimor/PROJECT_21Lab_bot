import { useEffect, useState } from "react";
import { api, type Quest } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function QuestsPage() {
  const [quests, setQuests] = useState<Quest[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api
      .quests()
      .then((data) => setQuests(data.quests))
      .catch((e) => setError(e.message));
  };

  useEffect(load, []);

  return (
    <Layout title="Квесты">
      {error && <ErrorBox message={error} />}
      {!quests.length && !error && <Loading />}
      {quests.map((quest) => (
        <Card key={quest.id}>
          <h3>{quest.title}</h3>
          <p>{quest.description}</p>
          <p>Награда: {quest.reward} 🙏</p>
          <Button
            variant={quest.joined ? "danger" : "primary"}
            onClick={async () => {
              if (quest.joined) await api.leaveQuest(quest.id);
              else await api.joinQuest(quest.id);
              load();
            }}
          >
            {quest.joined ? "Выйти" : "Участвовать"}
          </Button>
        </Card>
      ))}
    </Layout>
  );
}
