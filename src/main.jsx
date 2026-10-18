import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import LandingPage from "./pages/LandingPage";
import NotFound from "./pages/NotFound";

import Login from "./features/auth/pages/Login";
import Signup from "./features/auth/pages/Signup";
import { AuthProvider } from "./features/auth/AuthContext";
import { AssistantProvider } from "./features/assistant/AssistantContext";

import ProtectedRoute from "./components/ProtectedRoute";
import { FundsProvider } from "./features/dashboard/FundsContext";
import { Toaster } from "sonner";
import { Spinner } from "@/components/ui/spinner";
import ErrorBoundary from "./components/ErrorBoundary";

/* Lazy-load the dashboard pages so the landing page stays light. */
const Dashboard = lazy(() => import("./features/dashboard/pages/Dashboard"));
const DashboardHome = lazy(() => import("./features/dashboard/pages/DashboardHome"));
const Holdings = lazy(() => import("./features/dashboard/pages/Holdings"));
const Markets = lazy(() => import("./features/dashboard/pages/Markets"));
const Positions = lazy(() => import("./features/dashboard/pages/Positions"));
const Orders = lazy(() => import("./features/dashboard/pages/Orders"));
const Funds = lazy(() => import("./features/dashboard/pages/Funds"));
const WatchList = lazy(() => import("./features/dashboard/pages/WatchList"));
const InstrumentDetail = lazy(() =>
  import("./features/dashboard/components/InstrumentDetail").then((m) => ({ default: m.InstrumentDetail })),
);
const InstrumentEmpty = lazy(() =>
  import("./features/dashboard/components/InstrumentDetail").then((m) => ({ default: m.InstrumentEmpty })),
);

import "./styles/index.css";
import "./pages/landing.css";
import { initTheme } from "./utils/theme";

// Before the first render, so a stored dark preference never flashes light.
initTheme();

// shown while a lazy page chunk downloads (first visit to that page only)
function PageChunkSpinner() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner className="size-5 text-muted-foreground" />
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AssistantProvider>
          <ErrorBoundary>
            <Suspense fallback={<PageChunkSpinner />}>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/signup" element={<Signup />} />
                <Route path="/login" element={<Login />} />

                <Route
                  path="/dashboard"
                  element={
                    <ProtectedRoute>
                      <FundsProvider>
                        <Dashboard />
                      </FundsProvider>
                    </ProtectedRoute>
                  }
                >
                  <Route index element={<DashboardHome />} />
                  <Route path="holdings" element={<Holdings />} />
                  <Route path="markets" element={<Markets />} />
                  <Route path="positions" element={<Positions />} />
                  <Route path="orders" element={<Orders />} />
                  <Route path="watchlist" element={<WatchList />}>
                    {/* The detail pane fills WatchList's <Outlet />; the index is
                        the placeholder before a symbol is picked. */}
                    <Route index element={<InstrumentEmpty />} />
                    <Route path=":symbol" element={<InstrumentDetail />} />
                  </Route>
                  <Route path="funds" element={<Funds />} />
                </Route>

                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
              {/* Sonner's Toaster — toast() calls were silently dropped without it. */}
              <Toaster position="bottom-right" toastOptions={{ duration: 2500 }} />
          </ErrorBoundary>
        </AssistantProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>
);


