import { createContext, useContext, useState, useEffect } from "react";
import {
  getMe,
  login as loginRequest,
  logout as logoutRequest,
  signup as signupRequest,
} from "@/services/api";

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMe()
      .then((data) => setUser(data.user))
      .catch(() => {
        // no valid session cookie — stay logged out
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const signup = async (formData) => {
    const data = await signupRequest(formData);
    setUser(data.user);
    return data;
  };

  const login = async (formData) => {
    const data = await loginRequest(formData);
    setUser(data.user);
    return data;
  };

  const logout = async () => {
    await logoutRequest();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, signup, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
