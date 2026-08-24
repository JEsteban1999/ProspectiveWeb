/* PROSPECTIVE Web — root: splash → Login/Signup → Pacientes → Sesión → Solicitudes. */

import { useState } from "react";
import { api } from "./api/client";
import type { PatientSummary, StudyCard, StudySummary } from "./api/types";
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
  const { user, ready, expiredNotice } = useAuth();
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

  // Enter the pipeline for a clinical case: patient + case are known upfront, so
  // the upload panel no longer has to ask which case the DICOM belongs to.
  const planCase = (study: StudySummary, p: PatientSummary) => {
    planning.reset();
    planning.setPatient(p);
    planning.setCase(study.id, study.dx_principal || study.description || `Caso ${study.id}`);
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
      planning.setCase(study.case_id || null, study.dx_principal || study.description);
      planning.setImagingStudyId(study.id);
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
      // A resumed session keeps planning the same case and acquisition, so the
      // breadcrumb and the next "Guardar progreso" don't lose that link.
      planning.setCase(r.study_id, r.study_label);
      planning.setImagingStudyId(r.imaging_study_id);
      setPatient(p);
      planning.setSession(r.session_id);
      // The volume came back with the snapshot; mirror its series so step 1
      // shows the study instead of an empty drop zone.
      planning.setSeries(r.series);
      if (r.has_segmentation && r.mesh_url) {
        planning.setSegmentation({
          mesh_url: r.mesh_url, vertices: r.n_vertices, faces: r.n_faces,
          voxel_fraction: null, strategy: "restaurada", is_dsa: false,
          // The mesh came back from a snapshot; no cleanup ran now, so there is
          // nothing discarded to report.
          kept_fraction: 1, fragments_removed: 0, largest_removed_mm3: 0, downsample_factor: 1,
        });
      }
      // The centreline geometry comes back with the snapshot; without this the
      // store stays empty and the centreline-guided stent asks to extract one
      // that already exists (a ~30 s recomputation for nothing).
      if (r.centerline_mesh_url) {
        planning.setCenterlineMesh(r.centerline_mesh_url);
        planning.setCenterlineArcMm(r.centerline_arc_mm || null);
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
    // A session that expired mid-study explains itself on the login screen.
    view = (
      <Login
        onLogin={() => { setLoadingIn(true); setScreen("patients"); }}
        onSignup={() => setScreen("signup")}
        notice={loginNotice ?? expiredNotice}
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
    view = <Patients onOpenPatient={openPatient} onResume={resumeSession} onPlanCase={planCase} onOpenStudy={(s) => void openStudy(s)} onOpenPending={() => setScreen("pending")} />;
  else if (effective === "studies") view = <Studies onOpen={(s) => void openStudy(s)} onBack={() => setScreen("patients")} />;
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
