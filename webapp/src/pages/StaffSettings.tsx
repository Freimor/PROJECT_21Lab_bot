import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card, ErrorBox, Layout, Loading } from "../components";

export default function StaffSettingsPage() {
  const [settings, setSettings] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.staffSettings().then(setSettings).catch((e) => setError(e.message));
  }, []);

  if (!settings && !error) return <Layout><Loading /></Layout>;

  return (
    <Layout title="Настройки">
      {error && <ErrorBox message={error} />}
      {settings &&
        Object.entries(settings).map(([key, value]) => (
          <Card key={key}>
            <div className="list-item">
              <span>{key}</span>
              <span>{value}</span>
            </div>
            <Button
              variant="secondary"
              onClick={async () => {
                const next = prompt(`Новое значение для ${key}`, String(value));
                if (next) {
                  await api.staffPatchSetting(key, Number(next));
                  setSettings({ ...settings, [key]: Number(next) });
                }
              }}
            >
              Изменить
            </Button>
          </Card>
        ))}
      <Button
        variant="danger"
        onClick={async () => {
          if (confirm("Перезагрузить бота?")) await api.staffReboot();
        }}
      >
        Reboot
      </Button>
    </Layout>
  );
}
