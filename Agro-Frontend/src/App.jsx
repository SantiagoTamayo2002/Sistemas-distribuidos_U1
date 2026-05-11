// ==============================================================================
// ARCHIVO: App.jsx
// ==============================================================================
// DESCRIPCIÓN:
// Componente raíz de la aplicación. Maneja el estado de autenticación y 
// decide si renderizar la pantalla de Login o el Dashboard principal.
// ==============================================================================

import { useState, useEffect } from 'react';
import Login from './components/Login';
import Dashboard from './components/Dashboard';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Verificar si hay una sesión activa al cargar la aplicación
  useEffect(() => {
    const token = localStorage.getItem('agrosmart_token');
    if (token) {
      setIsAuthenticated(true);
    }
  }, []);

  const handleLoginSuccess = () => {
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem('agrosmart_token');
    localStorage.removeItem('agrosmart_user');
    setIsAuthenticated(false);
  };

  return (
    <>
      {isAuthenticated ? (
        <Dashboard onLogout={handleLogout} />
      ) : (
        <Login onLoginSuccess={handleLoginSuccess} />
      )}
    </>
  );
}

export default App;
