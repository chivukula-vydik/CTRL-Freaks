import { useEffect, useState } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { api } from './api/client';
import { Sidebar } from './components/Sidebar';
import QueuePage from './pages/QueuePage';
import ReviewPage from './pages/ReviewPage';
import BlockedPage from './pages/BlockedPage';
import PolicyPage from './pages/PolicyPage';
import AuditPage from './pages/AuditPage';

function Layout() {
  const location = useLocation();
  const [count, setCount] = useState<number>();
  const [targets, setTargets] = useState<{ review?: string; blocked?: string }>({});

  // Refresh the sidebar badge whenever the route changes (e.g. after approving).
  useEffect(() => {
    api.getQueue().then((q) => {
      setCount(q.summary.awaitingReview);
      // sidebar links point at real drafts, not a fixed sample customer
      setTargets({
        review: q.items.find((i) => i.status === 'ready' || i.status === 'attention')?.customerId,
        blocked: q.items.find((i) => i.status === 'blocked')?.customerId,
      });
    }).catch(() => setCount(undefined));
  }, [location.pathname]);

  return (
    <div className="shell">
      <Sidebar queueCount={count} targets={targets} />
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<QueuePage />} />
        <Route path="review/:customerId" element={<ReviewPage />} />
        <Route path="blocked/:customerId" element={<BlockedPage />} />
        <Route path="policy" element={<PolicyPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
