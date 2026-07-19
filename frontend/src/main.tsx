import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import "./index.css";
import { AuthProvider, RequireAdmin, RequireAuth } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import Account from "./routes/Account";
import Chat from "./routes/Chat";
import Login from "./routes/Login";
import Signup from "./routes/Signup";
import Verify from "./routes/Verify";

// The admin area is loaded on demand. It pulls in charting, which most users
// never see — and on the hardware this deploys to, the bytes not sent are the
// cheapest optimization available.
const AdminLayout = lazy(() => import("./routes/admin/AdminLayout"));
const Overview = lazy(() => import("./routes/admin/Overview"));
const Users = lazy(() => import("./routes/admin/Users"));
const UserDetail = lazy(() => import("./routes/admin/UserDetail"));
const Limits = lazy(() => import("./routes/admin/Limits"));
const System = lazy(() => import("./routes/admin/System"));

function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
    </div>
  );
}

/** Wraps a page in the signed-in shell. */
const app = (element: React.ReactNode) => (
  <RequireAuth>
    <AppShell>{element}</AppShell>
  </RequireAuth>
);

const lazyPage = (element: React.ReactNode) => (
  <Suspense fallback={<Loading />}>{element}</Suspense>
);

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/signup", element: <Signup /> },
  { path: "/verify", element: <Verify /> },

  { path: "/", element: <Navigate to="/chat" replace /> },
  { path: "/chat", element: app(<Chat />) },
  // The same component for both: the thread id is a route param, so opening a
  // conversation is a navigation rather than a state change — which makes the
  // back button and a shared link both work.
  { path: "/chat/:threadId", element: app(<Chat />) },
  { path: "/account", element: app(<Account />) },

  {
    path: "/admin",
    element: (
      <RequireAdmin>
        <AppShell>{lazyPage(<AdminLayout />)}</AppShell>
      </RequireAdmin>
    ),
    children: [
      { index: true, element: lazyPage(<Overview />) },
      { path: "users", element: lazyPage(<Users />) },
      { path: "users/:userId", element: lazyPage(<UserDetail />) },
      { path: "limits", element: lazyPage(<Limits />) },
      { path: "system", element: lazyPage(<System />) },
    ],
  },

  { path: "*", element: <Navigate to="/chat" replace /> },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
