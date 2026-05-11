// ==============================================================================
// ARCHIVO: Login.jsx
// ==============================================================================
// DESCRIPCIÓN:
// Componente de pantalla de inicio de sesión. Envía credenciales al API Gateway,
// y si son válidas, guarda el token JWT y los datos del usuario en localStorage.
// ==============================================================================

import { useState } from 'react';
import { API_GATEWAY_URL } from '../config';

export default function Login({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_GATEWAY_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (response.ok && data.status === 'ok') {
        // Guardar token y usuario en localStorage
        localStorage.setItem('agrosmart_token', data.token);
        localStorage.setItem('agrosmart_user', JSON.stringify(data.usuario));
        
        // Notificar a App.jsx que el login fue exitoso
        onLoginSuccess();
      } else {
        setError(data.mensaje || 'Error al iniciar sesión');
      }
    } catch (err) {
      setError('Error de conexión con el servidor: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="card login-card">
        <div className="login-header">
          <h1>🌱 Agro-Smart</h1>
          <p>Sistema de Monitoreo de Riego</p>
        </div>

        {error && <div className="error-message">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Usuario</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              placeholder="Ej: admin o juan_agricultor"
            />
          </div>
          
          <div className="form-group">
            <label>Contraseña</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button 
            type="submit" 
            className="btn" 
            style={{ width: '100%', marginTop: '10px' }}
            disabled={isLoading}
          >
            {isLoading ? 'Iniciando sesión...' : 'Ingresar al Sistema'}
          </button>
        </form>
      </div>
    </div>
  );
}
