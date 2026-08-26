/* Navigation context — lets any component (e.g. the Topbar) change the active
   screen without prop-drilling.

   Every screen has a URL under /app. Before this the active screen lived in a
   `useState`, so the browser's Back button walked out of the application
   entirely, a refresh always landed on the patient list, and there was no link
   to send a colleague. The Router keeps `screen` and the location in sync. */

import { createContext, useContext } from "react";

export type Screen = "login" | "signup" | "patients" | "studies" | "workspace" | "pending" | "audit" | "users";

/** Screen → path segment under /app. Spanish, because the UI is. */
export const SCREEN_PATH: Record<Screen, string> = {
  login: "/app/entrar",
  signup: "/app/registro",
  patients: "/app/pacientes",
  studies: "/app/estudios",
  workspace: "/app/sesion",
  pending: "/app/solicitudes",
  users: "/app/usuarios",
  audit: "/app/auditoria",
};

const PATH_SCREEN: Record<string, Screen> = Object.fromEntries(
  Object.entries(SCREEN_PATH).map(([s, p]) => [p, s as Screen]),
) as Record<string, Screen>;

/** Which screen a pathname names; `patients` is the landing screen of /app. */
export function screenFromPath(pathname: string): Screen {
  const clean = pathname.replace(/\/+$/, "") || "/app";
  return PATH_SCREEN[clean] ?? "patients";
}

interface Nav {
  screen: Screen;
  go: (s: Screen) => void;
}

const NavContext = createContext<Nav>({ screen: "login", go: () => {} });

export const NavProvider = NavContext.Provider;

export function useNav(): Nav {
  return useContext(NavContext);
}
