import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { DocumentsPage } from "./pages/DocumentsPage";
import { GeneratePage } from "./pages/GeneratePage";
import { LoginPage } from "./pages/LoginPage";
import { QuestionsPage } from "./pages/QuestionsPage";
import { SetDetailPage } from "./pages/SetDetailPage";
import { SetsPage } from "./pages/SetsPage";

/** Signed-in teachers only. This hides screens; the API enforces the role on every call. */
function RequireTeacher() {
  const { state, logout } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <p className="narrow">Loading&hellip;</p>;
  if (state.status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (state.role !== "teacher") {
    return (
      <main className="narrow">
        <h1>Teachers only</h1>
        <p>This app is for teacher accounts. Ask an administrator for a teacher account.</p>
        <button type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </main>
    );
  }
  return <Layout />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireTeacher />}>
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/generate" element={<GeneratePage />} />
        <Route path="/questions" element={<QuestionsPage />} />
        <Route path="/sets" element={<SetsPage />} />
        <Route path="/sets/:setId" element={<SetDetailPage />} />
        <Route path="*" element={<Navigate to="/documents" replace />} />
      </Route>
    </Routes>
  );
}
