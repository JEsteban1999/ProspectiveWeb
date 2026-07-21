/* PROSPECTIVE Web — root: splash → Login/Signup → Pacientes → Sesión → Solicitudes. */

import { useEffect, useState } from "react";
import type { PatientSummary } from "./api/types";
import { Login } from "./pages/Login";
import { Signup } from "./pages/Signup";
import { Patients } from "./pages/Patients";
import { Workspace } from "./pages/Workspace";
import { PendingRequests } from "./pages/PendingRequests";
import { AuditTrail } from "./pages/AuditTrail";
import { VideoSplash } from "./components/VideoSplash";
import { LoadingScreen } from "./components/LoadingScreen";
import { AuthProvider, useAuth } from "./store/auth";
import { PlanningProvider, usePlanning } from "./store/planning";
import { NavProvider } from "./store/nav";
import type { Screen } from "./store/nav";

function Router({ splashDone }: { splashDone: boolean }) {
  const { user, ready } = useAuth();
  const planning = usePlanning();
  const [screen, setScreen] = useState<Screen>("login");
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [loadingIn, setLoadingIn] = useState(false);
  const [entryChecked, setEntryChecked] = useState(false);
  const [pendingEntryLoad, setPendingEntryLoad] = useState(false);

  // Entrada desde la landing: si ya hay sesión, el login se salta, así que aquí
  // marcamos la carga pendiente. Si NO hay sesión, se limpia la señal y la carga
  // la dispara el login tras autenticarse (sin duplicarla).
  useEffect(() => {
    if (!ready || entryChecked) return;
    setEntryChecked(true);
    if (sessionStorage.getItem("prospective.enterLoading") === "1") {
      sessionStorage.removeItem("prospective.enterLoading");
      if (user) setPendingEntryLoad(true);
    }
  }, [ready, user, entryChecked]);

  // Arranca la carga de entrada solo cuando el splash ya no está → en la primera
  // entrada de la sesión se ven en secuencia: splash → carga → Pacientes.
  useEffect(() => {
    if (pendingEntryLoad && splashDone) {
      setPendingEntryLoad(false);
      setLoadingIn(true);
    }
  }, [pendingEntryLoad, splashDone]);

  if (!ready) return null; // restoring stored token

  // When logged out, only login/signup are reachable.
  const loggedOut: Screen = screen === "signup" ? "signup" : "login";
  const effective: Screen = user ? (screen === "login" || screen === "signup" ? "patients" : screen) : loggedOut;

  const openPatient = (p: PatientSummary) => {
    planning.reset();
    planning.setPatient(p);
    setPatient(p);
    setScreen("workspace");
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
    view = <Patients onOpenPatient={openPatient} onOpenPending={() => setScreen("pending")} />;
  else if (effective === "pending") view = <PendingRequests onBack={() => setScreen("patients")} />;
  else if (effective === "audit") view = <AuditTrail onBack={() => setScreen("patients")} />;
  else view = <Workspace patient={patient} onBack={() => setScreen("patients")} onFinish={finish} />;

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
  // Show the intro splash only once per browser session — otherwise it replays
  // every time the user bounces between the landing (/) and the app (/app).
  const [splashDone, setSplashDone] = useState(() => sessionStorage.getItem(SPLASH_KEY) === "1");
  return (
    <AuthProvider>
      <PlanningProvider>
        {!splashDone && (
          <VideoSplash
            onDone={() => {
              sessionStorage.setItem(SPLASH_KEY, "1");
              setSplashDone(true);
            }}
          />
        )}
        <Router splashDone={splashDone} />
      </PlanningProvider>
    </AuthProvider>
  );
}
