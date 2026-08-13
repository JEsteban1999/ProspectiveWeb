/* Navigation context — lets any component (e.g. the Topbar) change the active
   screen without prop-drilling. The App Router provides the `go` function. */

import { createContext, useContext } from "react";

export type Screen = "login" | "signup" | "patients" | "studies" | "workspace" | "pending" | "audit" | "users";

interface Nav {
  screen: Screen;
  go: (s: Screen) => void;
}

const NavContext = createContext<Nav>({ screen: "login", go: () => {} });

export const NavProvider = NavContext.Provider;

export function useNav(): Nav {
  return useContext(NavContext);
}
