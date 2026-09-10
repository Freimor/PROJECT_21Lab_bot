import { useApp } from "./context";

export function Layout({ children, title }: { children: React.ReactNode; title?: string }) {
  const { me } = useApp();
  return (
    <div className="app">
      <header className="header">
        <a href="#/" className="logo">
          Lab21
        </a>
        {me && (
          <div className="header-meta">
            <span>{me.balance} 🙏</span>
            <span>{me.respect} ❇</span>
          </div>
        )}
      </header>
      {title && <h1 className="page-title">{title}</h1>}
      <main className="main">{children}</main>
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">{message}</div>;
}

export function Card({ children }: { children: React.ReactNode }) {
  return <div className="card">{children}</div>;
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger";
}) {
  return (
    <button
      type="button"
      className={`btn btn-${variant}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export function Loading() {
  return <div className="loading">Загрузка…</div>;
}
