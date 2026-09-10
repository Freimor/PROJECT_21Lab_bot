import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Layout, Loading } from "../components";

export default function FaqArticlePage() {
  const { slug } = useParams();
  const [html, setHtml] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    api
      .getFaqPage(slug)
      .then((data) => {
        setTitle(data.title);
        setHtml(data.html);
      })
      .catch((e) => setError(String(e.message)));
  }, [slug]);

  return (
    <Layout title={title || "FAQ"}>
      {error && <ErrorBox message={error} />}
      {!html && !error && <Loading />}
      <div className="faq-body" dangerouslySetInnerHTML={{ __html: html }} />
    </Layout>
  );
}
