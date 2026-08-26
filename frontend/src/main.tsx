import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import { Landing } from "./pages/Landing";
import { ThemeProvider } from "./store/theme";
import "./styles/index.css";

// A DATA router (createBrowserRouter), not <BrowserRouter>: only this flavour
// supports useBlocker, which is what lets the workspace stop the browser's Back
// button when the session has unsaved results. With the old router a Back press
// walked out of the application and the work was gone without a prompt.
const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/app/*", element: <App /> },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  </StrictMode>
);
