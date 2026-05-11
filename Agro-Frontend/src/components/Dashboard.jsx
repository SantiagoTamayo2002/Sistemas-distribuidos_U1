// ==============================================================================
// ARCHIVO: Dashboard.jsx
// ==============================================================================
// DESCRIPCIÓN:
// Interfaz principal de monitoreo para el agricultor.
// - Muestra tarjetas resumen por parcela.
// - Muestra una tabla con las últimas lecturas.
// - Consulta periódicamente el estado del sistema y los últimos datos vía el Gateway.
// - Maneja expiración de sesión redirigiendo al login.
// ==============================================================================

import { useState, useEffect, useCallback } from 'react';
import { API_GATEWAY_URL } from '../config';

export default function Dashboard({ onLogout }) {
  const [lecturas, setLecturas] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdate, setLastUpdate] = useState(new Date());

  // Obtener usuario del localStorage
  const user = JSON.parse(localStorage.getItem('agrosmart_user') || '{}');
  const token = localStorage.getItem('agrosmart_token');

  const fetchStatus = async () => {
    try {
      const response = await fetch(`${API_GATEWAY_URL}/status`);
      const data = await response.json();
      setSystemStatus(data.microservicios || {});
    } catch (err) {
      console.error('Error fetching status:', err);
    }
  };

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_GATEWAY_URL}/lecturas`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (response.status === 401) {
        // Token expirado o inválido
        onLogout();
        return;
      }

      const data = await response.json();
      
      if (response.ok && data.status === 'ok') {
        // Invertir para mostrar los más recientes primero y tomar los últimos 20
        const recientes = data.lecturas.reverse().slice(0, 20);
        setLecturas(recientes);
        setLastUpdate(new Date());
      } else {
        setError(data.mensaje || 'Error al obtener datos');
      }
    } catch (err) {
      setError('Error de red: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  }, [token, onLogout]);

  // Ejecutar carga inicial y establecer intervalo de actualización (30s)
  useEffect(() => {
    fetchData();
    fetchStatus();

    const interval = setInterval(() => {
      fetchData();
      fetchStatus();
    }, 30000); // 30 segundos

    return () => clearInterval(interval);
  }, [fetchData]);

  // Agrupar la lectura más reciente de cada parcela activa para las tarjetas
  const getResumenPorParcela = () => {
    const resumen = {};
    lecturas.forEach(l => {
      if (!resumen[l.parcela_id]) {
        resumen[l.parcela_id] = l; // La primera que encontramos es la más reciente por el reverse()
      }
    });
    return Object.values(resumen);
  };

  const resumenes = getResumenPorParcela();

  return (
    <div className="container">
      <header className="dashboard-header">
        <div>
          <h1 style={{ color: 'var(--primary-color)' }}>🌱 Agro-Smart</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Panel de Control | Última actualización: {lastUpdate.toLocaleTimeString()}
          </p>
        </div>
        
        <div className="user-info">
          <span>Hola, <strong>{user.nombre_completo}</strong> ({user.rol})</span>
          <button className="btn btn-secondary" onClick={onLogout}>Cerrar Sesión</button>
        </div>
      </header>

      {/* ESTADO DEL SISTEMA */}
      <div className="system-status">
        {systemStatus && Object.entries(systemStatus).map(([name, status]) => (
          <div className="service-badge" key={name} title={status.url}>
            <span className={`dot ${status.activo ? 'dot-online' : 'dot-offline'}`}></span>
            {name.replace('_', ' ').toUpperCase()}
          </div>
        ))}
      </div>

      {error && <div className="error-message">{error}</div>}

      {/* TARJETAS DE RESUMEN POR PARCELA */}
      <div className="controls">
        <h2>Resumen de Parcelas</h2>
        <button className="btn" onClick={fetchData} disabled={isLoading}>
          {isLoading ? 'Actualizando...' : '↻ Actualizar Ahora'}
        </button>
      </div>

      <div className="summary-grid">
        {resumenes.length === 0 && !isLoading && (
          <p>No hay datos recientes disponibles para sus parcelas.</p>
        )}
        
        {resumenes.map(lectura => (
          <div className="card summary-card" key={lectura.parcela_id}>
            <h3>{lectura.parcela_id.replace('_', ' ').toUpperCase()}</h3>
            
            <div className="metric-row">
              <span>💧 Humedad Suelo:</span>
              <strong>{lectura.humedad_suelo}%</strong>
            </div>
            
            <div className="metric-row">
              <span>🌡️ Temperatura:</span>
              <strong>{lectura.temperatura}°C</strong>
            </div>

            <div className="metric-row">
              <span>Estado:</span>
              <span className={`status-indicator status-${lectura.estado_humedad.toLowerCase().replace('ó', 'o')}`}>
                {lectura.estado_humedad.toUpperCase()}
              </span>
            </div>

            <div className="recomendacion-banner">
              Acción: {lectura.recomendacion_riego}
            </div>
            
            <div style={{ marginTop: '15px', fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
              Nodo reporte: {lectura.nodo_id}
            </div>
          </div>
        ))}
      </div>

      {/* TABLA DE LECTURAS RECIENTES */}
      <div className="card">
        <h2>Últimas Lecturas Recibidas</h2>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Hora</th>
                <th>Parcela</th>
                <th>Nodo</th>
                <th>Hum. Suelo</th>
                <th>Temp.</th>
                <th>Estado</th>
                <th>Recomendación</th>
              </tr>
            </thead>
            <tbody>
              {lecturas.map((lectura, idx) => {
                const date = new Date(lectura.timestamp);
                return (
                  <tr key={idx}>
                    <td>{date.toLocaleTimeString()}</td>
                    <td>{lectura.parcela_id}</td>
                    <td>{lectura.nodo_id}</td>
                    <td>{lectura.humedad_suelo}%</td>
                    <td>{lectura.temperatura}°C</td>
                    <td>
                      <span className={`status-indicator status-${lectura.estado_humedad.toLowerCase().replace('ó', 'o')}`}>
                        {lectura.estado_humedad}
                      </span>
                    </td>
                    <td>{lectura.recomendacion_riego}</td>
                  </tr>
                );
              })}
              {lecturas.length === 0 && (
                <tr>
                  <td colSpan="7" style={{ textAlign: 'center' }}>Esperando datos de los sensores...</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
