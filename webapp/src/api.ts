const API_BASE = "/api/miniapp";

function initData(): string {
  return window.Telegram?.WebApp?.initData ?? "";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Authorization", `tma ${initData()}`);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail ?? payload.error ?? "Ошибка запроса");
  }
  return payload as T;
}

export type Me = {
  telegram_id: number;
  full_name: string;
  username?: string;
  bio?: string;
  balance: number;
  respect: number;
  rank: string;
  skill_ids: string[];
  skills: { id: string; title: string }[];
  job_notify_enabled: boolean;
  is_approved: boolean;
  is_staff: boolean;
  permissions: string[];
  join: { state: string; application?: Record<string, unknown> };
  publications_count?: number;
};

export const api = {
  getMe: () => request<Me>("/me"),
  patchMe: (body: Partial<{ bio: string; job_notify_enabled: boolean }>) =>
    request<Me>("/me", { method: "PATCH", body: JSON.stringify(body) }),
  getFaq: () => request<{ pages: { slug: string; title: string }[] }>("/faq"),
  getFaqPage: (slug: string) =>
    request<{ slug: string; title: string; html: string }>(`/faq/${slug}`),
  joinStatus: () => request<{ state: string }>("/join/status"),
  submitJoin: (body: {
    kind: "community" | "staff";
    bio?: string;
    skills_text?: string;
  }) => request("/join/applications", { method: "POST", body: JSON.stringify(body) }),
  shopProducts: () => request<{ products: Product[] }>("/shop/products"),
  shopOrder: (product_id: number, quantity: number) =>
    request("/shop/orders", {
      method: "POST",
      body: JSON.stringify({ product_id, quantity }),
    }),
  shopOrders: () => request<{ orders: Order[] }>("/shop/orders"),
  createJob: (body: {
    description: string;
    skill_ids: string[];
    price: number;
    assignee_note?: string;
  }) => request("/jobs", { method: "POST", body: JSON.stringify(body) }),
  myJobs: () =>
    request<{ as_customer: Job[]; as_assignee: Job[] }>("/jobs/mine"),
  getJob: (id: number) => request<Job>(`/jobs/${id}`),
  claimJob: (id: number) => request(`/jobs/${id}/claim`, { method: "POST", body: "{}" }),
  submitJobResult: (id: number, report: string) =>
    request(`/jobs/${id}/result`, {
      method: "POST",
      body: JSON.stringify({ report }),
    }),
  reviewJob: (id: number, approved: boolean) =>
    request(`/jobs/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  skillsCatalog: () =>
    request<{ skills: SkillCatalogItem[] }>("/me/skills/catalog"),
  addSkill: (skill_id: string) =>
    request("/me/skills", { method: "POST", body: JSON.stringify({ skill_id }) }),
  removeSkill: (skill_id: string) =>
    request(`/me/skills/${skill_id}`, { method: "DELETE" }),
  history: () => request<{ entries: HistoryEntry[] }>("/history"),
  transfer: (recipient_id: number, amount: number, reason: string) =>
    request("/transfers", {
      method: "POST",
      body: JSON.stringify({ recipient_id, amount, reason }),
    }),
  ritualBow: () => request<{ message: string; streak: number }>("/ritual/bow", { method: "POST", body: "{}" }),
  quests: () => request<{ quests: Quest[]; mine: Quest[] }>("/quests"),
  joinQuest: (id: number) => request(`/quests/${id}/join`, { method: "POST", body: "{}" }),
  leaveQuest: (id: number) => request(`/quests/${id}/leave`, { method: "POST", body: "{}" }),
  skillsBoard: () => request<{ skills: { id: string; title: string }[] }>("/skills/board"),
  skillBoardDetail: (id: string) =>
    request<{ members: { telegram_id: number; full_name: string }[]; text: string }>(
      `/skills/board/${id}`,
    ),
  mySubmissions: () => request<{ items: Submission[] }>("/submissions/mine"),
  submitPost: (kind: string, source_text: string) =>
    request("/submissions/posts", {
      method: "POST",
      body: JSON.stringify({ kind, source_text }),
    }),
  submitMeme: (file: File, caption: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("caption", caption);
    return request("/submissions/memes", { method: "POST", body: form });
  },
  staffDashboard: () => request<StaffDashboard>("/staff/dashboard"),
  staffContentQueue: () => request<{ items: Submission[] }>("/staff/content/queue"),
  staffContentAction: (id: number, action: string, note?: string) =>
    request(`/staff/content/${id}`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }),
  staffOrders: () => request<{ orders: Order[] }>("/staff/orders"),
  staffOrderAction: (id: number, action: string) =>
    request(`/staff/orders/${id}`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  staffApplications: () =>
    request<{ applications: Record<string, unknown>[] }>("/staff/people/applications"),
  staffApplicationAction: (id: number, action: string, note?: string) =>
    request(`/staff/people/applications/${id}`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }),
  staffSettings: () => request<Record<string, number>>("/staff/settings"),
  staffPatchSetting: (key: string, value: number) =>
    request("/staff/settings", {
      method: "PATCH",
      body: JSON.stringify({ key, value }),
    }),
  staffProducts: () => request<{ products: Product[] }>("/staff/products"),
  staffGrant: (target_id: number, amount: number, reason: string) =>
    request("/staff/grants", {
      method: "POST",
      body: JSON.stringify({ target_id, amount, reason }),
    }),
  staffReboot: () => request("/staff/reboot", { method: "POST", body: "{}" }),
};

export type Product = {
  id: number;
  name: string;
  description: string;
  price: number;
  available: boolean;
  image_url?: string;
  kind: string;
};

export type Order = {
  id: number;
  product_name?: string;
  qty: number;
  total_price: number;
  status: string;
};

export type Job = {
  id: number;
  status: string;
  description: string;
  skill_ids: string[];
  price: number;
  customer_id: number;
  assignee_id?: number;
  result_text?: string;
};

export type SkillCatalogItem = {
  id: string;
  title: string;
  requires_validation: boolean;
  grace_price: number;
};

export type HistoryEntry = {
  created_at: string;
  delta: number;
  reason: string;
};

export type Quest = {
  id: number;
  title: string;
  description: string;
  status: string;
  reward: number;
  joined?: boolean;
};

export type Submission = {
  id: number;
  kind: string;
  status: string;
  source_text: string;
};

export type StaffDashboard = {
  pending_applications: number;
  moderation_queue: number;
  pending_orders: number;
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        ready: () => void;
        expand: () => void;
        close: () => void;
        themeParams: Record<string, string>;
        MainButton: {
          text: string;
          show: () => void;
          hide: () => void;
          onClick: (cb: () => void) => void;
          offClick: (cb: () => void) => void;
        };
      };
    };
  }
}
