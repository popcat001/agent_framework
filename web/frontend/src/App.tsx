import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { Layout } from "./components/Layout";
import { project } from "./config/project";

function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center" style={{ background: "var(--bg-primary)" }}>
        <div className="text-center">
          <img src={project.appLogo} alt={project.name} className="w-48 mx-auto mb-4" />
          <p style={{ color: "var(--text-secondary)" }}>Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center" style={{ background: "var(--bg-primary)" }}>
        <div className="text-center max-w-md px-8">
          <img src={project.appLogo} alt={project.name} className="w-72 mx-auto mb-6" />
          <p className="mb-4" style={{ color: "var(--text-secondary)" }}>
            Authentication required. Please ensure Azure AD authentication is configured on this App Service.
          </p>
        </div>
      </div>
    );
  }

  return <Layout />;
}

export function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
