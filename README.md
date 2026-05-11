# Agro-Smart - Sistema de Monitoreo de Riego Agrícola

Prueba de concepto (PoC) de un sistema distribuido para el monitoreo y control de riego en parcelas agrícolas utilizando sensores IoT, MQTT, microservicios Flask y un Dashboard en React.

## Arquitectura del Sistema

El sistema consta de 5 componentes diseñados para operar en diferentes PCs de una red local:

1. **Broker MQTT**: Mosquitto (infraestructura).
2. **iot_simulator.py**: Simulador de Nodos IoT que generan telemetría (Componente 1).
3. **ingestion_service.py**: Microservicio Flask que suscribe a MQTT y procesa los datos (Componente 2).
4. **auth_service.py**: Microservicio Flask para autenticación JWT (Componente 3).
5. **api_gateway.py**: API Gateway Flask que enruta y unifica peticiones (Componente 4).
6. **Dashboard React**: Interfaz de usuario (Componente 5).

## Requisitos Previos

- Python 3.8 o superior
- Node.js (para el dashboard React)
- Mosquitto MQTT Broker

### Instalar Mosquitto

- **Windows**: Descarga el instalador desde [mosquitto.org/download](https://mosquitto.org/download/).
- **Linux (Ubuntu/Debian)**: `sudo apt install mosquitto mosquitto-clients`
- **Mac**: `brew install mosquitto`

El broker debe estar corriendo en su puerto por defecto (1883).

### Instalar dependencias de Python

Abre una terminal en la carpeta raíz del proyecto y ejecuta:

```bash
pip install -r requirements.txt
```

## Configuración para Red Local (Múltiples PCs)

Para desplegar los componentes en diferentes máquinas, debes editar las constantes de configuración al inicio de cada archivo:

1. **Identifica las direcciones IP** de las PCs en la red local (ej. usando `ipconfig` en Windows o `ifconfig` en Linux).
2. **iot_simulator.py**:
   - Cambia `MQTT_BROKER_IP` a la IP de la PC donde corre Mosquitto.
3. **ingestion_service.py**:
   - Cambia `MQTT_BROKER_IP` a la IP de la PC donde corre Mosquitto.
4. **api_gateway.py**:
   - Cambia `AUTH_SERVICE_URL` a la IP y puerto de la PC donde corre `auth_service.py` (ej. `http://192.168.1.10:5002`).
   - Cambia `INGESTION_SERVICE_URL` a la IP y puerto de la PC donde corre `ingestion_service.py` (ej. `http://192.168.1.11:5001`).
5. **Dashboard React (`src/config.js`)**:
   - Cambia la URL del Gateway a la IP de la PC donde corre `api_gateway.py`.

## Orden de Ejecución

Es importante levantar los servicios en un orden lógico, aunque están diseñados para tolerar fallos y reconectar:

**1. Levantar el Broker MQTT**
Asegúrate de que el servicio Mosquitto esté en ejecución.

**2. Levantar Microservicios Base (en diferentes terminales o PCs)**
```bash
python auth_service.py
python ingestion_service.py
```

**3. Levantar el API Gateway**
```bash
python api_gateway.py
```

**4. Iniciar el Simulador IoT**
```bash
python iot_simulator.py
```
*(Deberías empezar a ver en la terminal cómo se publican los mensajes, y en la terminal de ingestion_service cómo se procesan).*

**5. Levantar el Dashboard React**
Abre una terminal en la carpeta `agrosmart-dashboard`:
```bash
npm install
npm start
```

## Credenciales de Acceso al Dashboard

El sistema tiene usuarios precargados en memoria:

- **Admin (acceso a todas las parcelas):**
  - Usuario: `admin`
  - Contraseña: `admin123`

- **Agricultor Juan (acceso a parcelas 01 y 02):**
  - Usuario: `juan_agricultor`
  - Contraseña: `campo2024`

- **Supervisora María (acceso a parcela 03):**
  - Usuario: `maria_supervisora`
  - Contraseña: `riego#456`
