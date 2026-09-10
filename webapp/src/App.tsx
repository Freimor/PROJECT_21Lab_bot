import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { AppProvider } from "./context";
import HomePage from "./pages/Home";
import FaqPage from "./pages/Faq";
import FaqArticlePage from "./pages/FaqArticle";
import JoinPage from "./pages/Join";
import ProfilePage from "./pages/Profile";
import ShopPage from "./pages/Shop";
import JobsPage from "./pages/Jobs";
import JobDetailPage from "./pages/JobDetail";
import OrderServicePage from "./pages/OrderService";
import SubmitPage from "./pages/Submit";
import QuestsPage from "./pages/Quests";
import SkillsPage from "./pages/Skills";
import TransferPage from "./pages/Transfer";
import HistoryPage from "./pages/History";
import StaffPage from "./pages/Staff";
import StaffContentPage from "./pages/StaffContent";
import StaffOrdersPage from "./pages/StaffOrders";
import StaffPeoplePage from "./pages/StaffPeople";
import StaffSettingsPage from "./pages/StaffSettings";
import "./styles.css";

function NavLinkItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "active" : undefined)}>
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <AppProvider>
      <HashRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/faq" element={<FaqPage />} />
          <Route path="/faq/:slug" element={<FaqArticlePage />} />
          <Route path="/join" element={<JoinPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/shop" element={<ShopPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/order" element={<OrderServicePage />} />
          <Route path="/submit" element={<SubmitPage />} />
          <Route path="/quests" element={<QuestsPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/transfer" element={<TransferPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/staff" element={<StaffPage />} />
          <Route path="/staff/content" element={<StaffContentPage />} />
          <Route path="/staff/orders" element={<StaffOrdersPage />} />
          <Route path="/staff/people" element={<StaffPeoplePage />} />
          <Route path="/staff/settings" element={<StaffSettingsPage />} />
        </Routes>
        <nav className="bottom-nav">
          <NavLinkItem to="/">Главная</NavLinkItem>
          <NavLinkItem to="/shop">Магазин</NavLinkItem>
          <NavLinkItem to="/jobs">Заказы</NavLinkItem>
          <NavLinkItem to="/profile">Профиль</NavLinkItem>
          <NavLinkItem to="/faq">FAQ</NavLinkItem>
        </nav>
      </HashRouter>
    </AppProvider>
  );
}
