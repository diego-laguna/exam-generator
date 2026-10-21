import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { RoleGate } from "./components/RoleGate";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ExamPage } from "./pages/ExamPage";
import { ExamSessionsPage } from "./pages/ExamSessionsPage";
import { ExamsPage } from "./pages/ExamsPage";
import { GeneratePage } from "./pages/GeneratePage";
import { JoinPage } from "./pages/JoinPage";
import { LoginPage } from "./pages/LoginPage";
import { QuestionsPage } from "./pages/QuestionsPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SamplesPage } from "./pages/SamplesPage";
import { SessionDashboardPage } from "./pages/SessionDashboardPage";
import { SetDetailPage } from "./pages/SetDetailPage";
import { SetsPage } from "./pages/SetsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { StatsPage } from "./pages/StatsPage";
import { UsersPage } from "./pages/UsersPage";
import { homeFor, isRole } from "./roles";

/** Signed-in users only. */
function RequireAuth() {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <p className="narrow">Loading&hellip;</p>;
  if (state.status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Layout />;
}

function Home() {
  const { state } = useAuth();
  const role = state.status === "authenticated" && isRole(state.role) ? state.role : null;
  return <Navigate to={homeFor(role)} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Students open this from the teacher's link; no account needed. */}
      <Route path="/join/:token" element={<JoinPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Home />} />

        {/* Any signed-in user */}
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/stats" element={<StatsPage />} />

        <Route element={<RoleGate roles={["teacher"]} />}>
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/generate" element={<GeneratePage />} />
          <Route path="/questions" element={<QuestionsPage />} />
          <Route path="/sets" element={<SetsPage />} />
          <Route path="/sets/:setId" element={<SetDetailPage />} />
          <Route path="/exam" element={<ExamSessionsPage />} />
          <Route path="/sessions/:sessionId" element={<SessionDashboardPage />} />
        </Route>

        <Route element={<RoleGate roles={["student"]} />}>
          <Route path="/exams" element={<ExamsPage />} />
          <Route path="/exams/:examId" element={<ExamPage />} />
          <Route path="/exams/:examId/results" element={<ResultsPage />} />
        </Route>

        <Route element={<RoleGate roles={["admin"]} />}>
          <Route path="/users" element={<UsersPage />} />
          <Route path="/samples" element={<SamplesPage />} />
        </Route>

        <Route path="*" element={<Home />} />
      </Route>
    </Routes>
  );
}
