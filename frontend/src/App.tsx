/* PROSPECTIVE Web — root: splash → Login/Signup → Pacientes → Sesión → Solicitudes. */

import { useState } from "react";
import { api } from "./api/client";
import type { PatientSummary, StudyCard } from "./api/types";
import { Login } from "./pages/Login";
import { Signup } from "./pages/Signup";
import { Patients } from "./pages/Patients";
import { Studies } from "./pages/Studies";
import { Workspace } from "./pages/Workspace";
import { PendingRequests } from "./pages/PendingRequests";
import { UsersAdmin } from "./pages/UsersAdmin";
import { AuditTrail } from "./pages/AuditTrail";
import { VideoSplash } from "./components/VideoSplash";
import { LoadingScreen } from "./components/LoadingScreen";
import { AuthProvider, useAuth } from "./store/auth";
import { PlanningProvider, usePlanning } from "./store/planning";
import { NavProvider } from "./store/nav";
import type { Screen } from "./store/nav";

function Router() {
  const { user, ready } = useAuth();
  const planning = usePlanning();
  const [screen, setScreen] = useState<Screen>("login");
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [loadingIn, setLoadingIn] = useState(false);
  const [resumeStep, setResumeStep] = useState(0);

  if (!ready) return null; // restoring stored token

  // When logged out, only login/signup are reachable.
  const loggedOut: Screen = screen === "signup" ? "signup" : "login";
  const effective: Screen = user ? (screen === "login" || screen === "signup" ? "patients" : screen) : loggedOut;

  const openPatient = (p: PatientSummary) => {
    planning.reset();
    planning.setPatient(p);
    setPatient(p);
    setResumeStep(0);
    setScreen("workspace");
  };

  // Open an archived study from the gallery: its DICOM is copied back into a
  // fresh session and the pipeline starts at step 1 with the volume loaded.
  const openStudy = async (study: StudyCard) => {
    setToast("Abriendo estudio…");
    try {
      const r = await api.openStudy(study.id);
      const patients = await api.listPatients();
      const p = patients.find((x) => x.id === study.patient_id) ?? null;
      planning.reset();
      planning.setPatient(p);
      setPatient(p);
      planning.setSession(r.session_id);
      // The backend already activated the best series; mirror it so step 1 shows
      // the study (without this the panel looks empty and "Continuar" is off).
      planning.setSeries(r.series[0] ?? null);
      setResumeStep(0);
      setToast(null);
      setScreen("workspace");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "No se pudo abrir el estudio");
      setTimeout(() => setToast(null), 3000);
    }
  };

  // Resume a saved study session: restore its files into a fresh live session,
  // rehydrate the store (mesh + downstream results are re-derived deterministically),
  // and open the workspace at the step it was saved on.
  const resumeSession = async (sessionId: string, p: PatientSummary) => {
    setToast("Restaurando sesión…");
    try {
      const r = await api.restoreSession(sessionId);
      planning.reset();
      planning.setPatient(p);
      setPatient(p);
      planning.setSession(r.session_id);
      if (r.has_segmentation && r.mesh_url) {
        planning.setSegmentation({
          mesh_url: r.mesh_url, vertices: r.n_vertices, faces: r.n_faces,
          voxel_fraction: null, strategy: "restaurada", is_dsa: false,
        });
      }
      // Replay downstream so the saved step shows its results (deterministic on
      // the restored mesh). Failures are non-fatal — the user can re-run a step.
      if (r.current_step >= 2) {
        try {
          const det = await api.detect(r.session_id);
          planning.setCandidates(det.candidates);
          planning.setSelectedCandidate(0);
        } catch { /* leave candidates empty */ }
      }
      if (r.current_step >= 3) {
        try { planning.setMorphometry(await api.morphometry(r.session_id)); }
        catch { /* leave morphometry empty */ }
      }
      setResumeStep(Math.min(Math.max(r.current_step, 0), 6));
      setToast(null);
      setScreen("workspace");
    } catch (e) {
      setToast(e instanceof Error ? e.message : "No se pudo restaurar la sesión");
      setTimeout(() => setToast(null), 3000);
    }
  };

  const finish = () => {
    setToast("✓ Sesión guardada y vinculada al paciente");
    setTimeout(() => {
      setToast(null);
      setScreen("patients");
    }, 1600);
  };

  let view;
  if (effective === "login")
    view = (
      <Login
        onLogin={() => { setLoadingIn(true); setScreen("patients"); }}
        onSignup={() => setScreen("signup")}
        notice={loginNotice}
      />
    );
  else if (effective === "signup")
    view = (
      <Signup
        onBack={() => { setLoginNotice(null); setScreen("login"); }}
        onDone={(msg) => { setLoginNotice(msg); setScreen("login"); }}
      />
    );
  else if (effective === "patients")
    view = <Patients onOpenPatient={openPatient} onResume={resumeSession} onOpenPending={() => setScreen("pending")} />;
  else if (effective === "studies") view = <Studies onOpen={(s) => void openStudy(s)} />;
  else if (effective === "pending") view = <PendingRequests onBack={() => setScreen("patients")} />;
  else if (effective === "users") view = <UsersAdmin onBack={() => setScreen("patients")} />;
  else if (effective === "audit") view = <AuditTrail onBack={() => setScreen("patients")} />;
  else view = <Workspace patient={patient} initialStep={resumeStep} onBack={() => setScreen("patients")} onFinish={finish} />;

  return (
    <NavProvider value={{ screen: effective, go: (s) => setScreen(s) }}>
    <div style={{ height: "100%", position: "relative" }}>
      {view}
      {loadingIn && <LoadingScreen onDone={() => setLoadingIn(false)} />}
      {toast && (
        <div
          style={{
            position: "fixed",
            top: 76,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 200,
            background: "var(--foreground)",
            color: "var(--background)",
            padding: "12px 22px",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-lg)",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {toast}
        </div>
      )}
    </div>
    </NavProvider>
  );
}

const SPLASH_KEY = "prospective.splashShown";

export default function App() {
  // El splash de intro se ve una sola vez por sesión, en la primera página que se
  // cargue (la landing lo muestra si entras por "/"; aquí si entras directo a /app).
  const [dismissed, setDismissed] = useState(() => sessionStorage.getItem(SPLASH_KEY) === "1");

  return (
    <AuthProvider>
      <PlanningProvider>
        {!dismissed && (
          <VideoSplash
            onDone={() => {
              sessionStorage.setItem(SPLASH_KEY, "1");
              setDismissed(true);
            }}
          />
        )}
        <Router />
      </PlanningProvider>
    </AuthProvider>
  );
}
