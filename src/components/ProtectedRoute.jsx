import { Navigate } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { Spinner } from "@/components/ui/spinner";

const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();

  // While the session check is in flight we can't tell yet whether the user is
  // logged in, so show a spinner instead of flashing the login page.
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

export default ProtectedRoute;
