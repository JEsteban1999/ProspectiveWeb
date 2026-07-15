import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import { Landing } from "./pages/Landing";
import { ThemeProvider } from "./store/theme";
import "./styles/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app/*" element={<App />} />
        </Routes>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>
);
