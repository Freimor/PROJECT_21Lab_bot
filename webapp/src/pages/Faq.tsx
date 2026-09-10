import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, ErrorBox, Layout, Loading } from "../components";

export default function FaqPage() {
  const [pages, setPages] = useState<{ slug: string; title: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getFaq().then((data) => setPages(data.pages)).catch((e) => setError(String(e.message)));
  }, []);

  return (
    <Layout title="FAQ">
      {error && <ErrorBox message={error} />}
      {!pages.length && !error && <Loading />}
      {pages.map((page) => (
        <Card key={page.slug}>
          <Link to={`/faq/${page.slug}`}>{page.title}</Link>
        </Card>
      ))}
    </Layout>
  );
}
