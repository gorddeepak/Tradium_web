import { createContext, useContext, useState, useEffect } from "react";
import axios from "axios";
import { BASE_URL } from "@/services/api";

const AuthContext = createContext();
const API_URL = `${BASE_URL}/auth`;

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const { data } = await axios.get(`${API_URL}/me`, {
          withCredentials: true,
        });
        setUser(data.user);
      } catch {
        // no valid session cookie — stay logged out
        setUser(null);
      } finally {
        setLoading(false);
      }
    };
    checkAuth();
  }, []);

  const signup = async (formData) => {
    const { data } = await axios.post(`${API_URL}/signup`, formData, { withCredentials: true });
    setUser(data.user);
    return data;
  };

  const login = async (formData) => {
  const { data } = await axios.post(
    `${API_URL}/login`,
    formData,
    { withCredentials: true }
  );

  setUser(data.user);
  return data;
};


  const logout = async () => {
    await axios.post(`${API_URL}/logout`, {}, { withCredentials: true });
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, signup, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);


