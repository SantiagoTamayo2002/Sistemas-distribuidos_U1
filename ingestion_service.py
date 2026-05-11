"""
================================================================================
ARCHIVO: ingestion_service.py
ROL EN LA ARQUITECTURA: Componente 2 — Servicio de Ingesta y Procesamiento
================================================================================
DESCRIPCIÓN:
    Este servidor Flask actúa como suscriptor MQTT y procesador de datos
    en tiempo real. Recibe las telemetrías publicadas por los nodos IoT,
    las valida, las enriquece con estado de riego, y las expone vía REST
    para ser consumidas por el API Gateway y el Dashboard.

    La suscripción MQTT corre en un hilo separado (threading) para no bloquear
    el servidor HTTP de Flask.

SECCIONES IMPORTANTES:
    - CONFIGURACIÓN: Constantes de puerto, broker y límites de almacenamiento.
    - CAMPOS_REQUERIDOS / RANGOS_VALIDOS: Esquema de validación de mensajes.
    - calcular_estado_humedad(): Clasifica el nivel de humedad del suelo.
    - calcular_recomendacion_riego(): Genera recomendación basada en estado.
    - procesar_mensaje(): Valida, enriquece y almacena un mensaje MQTT.
    - Hilo MQTT: Suscriptor a agrosmart/# que alimenta el almacén en memoria.
    - Endpoints Flask: /api/lecturas, /api/lecturas/<id>, /api/status, etc.

ALMACENAMIENTO: Lista circular en memoria (máx. 100 registros).
PROTOCOLO ENTRADA: MQTT (suscripción a agrosmart/#)
PROTOCOLO SALIDA:  HTTP REST JSON con CORS abierto
DEPENDENCIAS: flask, flask-cors, paho-mqtt
================================================================================
"""

import json
import time
import threading
import logging
from datetime import datetime, timezone
from collections import deque

import paho.mqtt.client as mqtt
from flask import Flask, jsonify
from flask_cors import CORS

# ==============================================================================
# CONFIGURACIÓN — Editar estas constantes según el entorno de despliegue
# ==============================================================================
FLASK_PORT       = 5001              # Puerto del servidor Flask
MQTT_BROKER_IP   = "localhost"       # IP del broker Mosquitto
MQTT_BROKER_PORT = 1883              # Puerto del broker
MQTT_TOPIC       = "agrosmart/#"     # Suscripción wildcard para todos los nodos
MAX_REGISTROS    = 100               # Máximo de lecturas almacenadas en memoria
MQTT_RECONNECT_DELAY = 3             # Segundos entre intentos de reconexión

# ==============================================================================
# ESQUEMA DE VALIDACIÓN DE MENSAJES
# ==============================================================================

CAMPOS_REQUERIDOS = [
    "parcela_id", "nodo_id", "timestamp",
    "humedad_suelo", "temperatura", "humedad_aire",
    "rssi",
]

# Rangos aceptables para cada campo numérico
RANGOS_VALIDOS = {
    "humedad_suelo": (0.0,   100.0),
    "temperatura":   (-20.0, 60.0),
    "humedad_aire":  (0.0,   100.0),
    "rssi":          (-120.0, 0.0),
}

# ==============================================================================
# ALMACÉN EN MEMORIA
# ==============================================================================

# deque con maxlen actúa como buffer circular de tamaño fijo
lecturas_almacenadas = deque(maxlen=MAX_REGISTROS)
contador_mensajes    = 0          # Total de mensajes recibidos (incluyendo inválidos)
contador_procesados  = 0          # Mensajes válidos y procesados
lock_lecturas        = threading.Lock()  # Mutex para acceso seguro desde múltiples hilos

# ==============================================================================
# CONFIGURACIÓN DE LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AgroSmart-Ingestion")


# ==============================================================================
# LÓGICA DE PROCESAMIENTO Y CLASIFICACIÓN
# ==============================================================================

def calcular_estado_humedad(humedad_suelo: float) -> str:
    """
    Clasifica el nivel de humedad del suelo en cuatro categorías.

    Criterios:
        < 30%   → "crítico"  (riesgo de estrés hídrico severo)
        30-45%  → "bajo"     (riego necesario pronto)
        45-70%  → "óptimo"   (rango ideal para la mayoría de cultivos)
        > 70%   → "exceso"   (riesgo de encharcamiento y enfermedades)

    Args:
        humedad_suelo: Porcentaje de humedad volumétrica del suelo.

    Returns:
        str con la categoría de humedad.
    """
    if humedad_suelo < 30.0:
        return "crítico"
    elif humedad_suelo < 45.0:
        return "bajo"
    elif humedad_suelo <= 70.0:
        return "óptimo"
    else:
        return "exceso"


def calcular_recomendacion_riego(estado_humedad: str) -> str:
    """
    Genera una recomendación de acción de riego basada en el estado de humedad.

    Args:
        estado_humedad: Resultado de calcular_estado_humedad().

    Returns:
        str con la recomendación de riego.
    """
    mapa_recomendaciones = {
        "crítico": "Regar inmediatamente",
        "bajo":    "Regar pronto",
        "óptimo":  "No regar",
        "exceso":  "Reducir riego",
    }
    return mapa_recomendaciones.get(estado_humedad, "Sin datos")


def validar_mensaje(datos: dict) -> tuple[bool, str]:
    """
    Valida que el mensaje MQTT tenga todos los campos requeridos y
    que los valores numéricos estén dentro de rangos aceptables.

    Args:
        datos: Diccionario con el payload del mensaje MQTT.

    Returns:
        Tupla (es_valido: bool, razon_invalido: str).
        Si es_valido=True, razon_invalido es una cadena vacía.
    """
    # 1. Verificar campos requeridos
    for campo in CAMPOS_REQUERIDOS:
        if campo not in datos:
            return False, f"Campo faltante: '{campo}'"

    # 2. Verificar rangos numéricos
    for campo, (minimo, maximo) in RANGOS_VALIDOS.items():
        valor = datos.get(campo)
        try:
            valor_float = float(valor)
        except (TypeError, ValueError):
            return False, f"Valor no numérico en '{campo}': {valor}"

        if not (minimo <= valor_float <= maximo):
            return False, (
                f"Valor fuera de rango en '{campo}': {valor_float} "
                f"(esperado: {minimo}–{maximo})"
            )

    return True, ""


def procesar_mensaje(payload_str: str, topic: str):
    """
    Procesamiento completo de un mensaje MQTT recibido:
        1. Deserializa el JSON.
        2. Valida campos y rangos.
        3. Enriquece con estado de humedad y recomendación de riego.
        4. Agrega metadatos de procesamiento.
        5. Almacena en el buffer en memoria (thread-safe).

    Args:
        payload_str: Cadena JSON del mensaje MQTT.
        topic:       Topic MQTT del mensaje (para logging).
    """
    global contador_mensajes, contador_procesados

    with lock_lecturas:
        contador_mensajes += 1

    # Deserializar JSON
    try:
        datos = json.loads(payload_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Payload JSON inválido en topic {topic}: {e}")
        return

    # Validar mensaje
    es_valido, razon = validar_mensaje(datos)
    if not es_valido:
        logger.warning(f"Mensaje inválido de {topic}: {razon}")
        return

    # Enriquecer con estado y recomendación
    estado_humedad     = calcular_estado_humedad(datos["humedad_suelo"])
    recomendacion      = calcular_recomendacion_riego(estado_humedad)

    lectura_procesada = {
        **datos,
        "estado_humedad":      estado_humedad,
        "recomendacion_riego": recomendacion,
        "timestamp_ingestion": datetime.now(timezone.utc).isoformat(),
        "topic_origen":        topic,
    }

    # Almacenar de forma thread-safe
    with lock_lecturas:
        lecturas_almacenadas.append(lectura_procesada)
        contador_procesados += 1

    logger.info(
        f"✓ Procesado [{datos['parcela_id']}/{datos['nodo_id']}] "
        f"Humedad: {datos['humedad_suelo']}% → {estado_humedad} | "
        f"Acción: {recomendacion}"
    )


# ==============================================================================
# CLIENTE MQTT (corre en hilo separado)
# ==============================================================================

def on_connect_ingestion(client, userdata, flags, rc):
    """Callback de conexión: suscribe al topic wildcard tras conectar."""
    if rc == 0:
        logger.info(f"Conectado al broker MQTT {MQTT_BROKER_IP}:{MQTT_BROKER_PORT}")
        client.subscribe(MQTT_TOPIC, qos=1)
        logger.info(f"Suscrito al topic: {MQTT_TOPIC}")
    else:
        logger.warning(f"Fallo de conexión MQTT, código: {rc}")


def on_message_ingestion(client, userdata, msg):
    """Callback de mensaje: procesa cada telemetría recibida."""
    try:
        payload_str = msg.payload.decode("utf-8")
        procesar_mensaje(payload_str, msg.topic)
    except Exception as e:
        logger.error(f"Error procesando mensaje de {msg.topic}: {e}")


def on_disconnect_ingestion(client, userdata, rc):
    """Callback de desconexión: registra el evento."""
    if rc != 0:
        logger.warning(f"Desconexión inesperada del broker MQTT (código {rc})")


def iniciar_cliente_mqtt():
    """
    Inicia el cliente MQTT en un hilo de background con reconexión automática.
    Esta función se ejecuta en un daemon thread para no bloquear Flask.
    """
    client = mqtt.Client(client_id="agrosmart-ingestion-service")
    client.on_connect    = on_connect_ingestion
    client.on_message    = on_message_ingestion
    client.on_disconnect = on_disconnect_ingestion
    client.reconnect_delay_set(min_delay=2, max_delay=120)

    while True:
        try:
            logger.info(f"Conectando al broker MQTT {MQTT_BROKER_IP}:{MQTT_BROKER_PORT}...")
            client.connect(MQTT_BROKER_IP, MQTT_BROKER_PORT, 60)
            client.loop_forever()  # Bloquea el hilo, gestiona reconexiones automáticamente
        except Exception as e:
            logger.error(
                f"Error de conexión MQTT: {e}. "
                f"Reintentando en {MQTT_RECONNECT_DELAY}s..."
            )
            time.sleep(MQTT_RECONNECT_DELAY)


# ==============================================================================
# APLICACIÓN FLASK
# ==============================================================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # CORS abierto para toda la API


@app.route("/api/lecturas", methods=["GET"])
def get_lecturas():
    """
    GET /api/lecturas
    Retorna todos los registros procesados almacenados en memoria (máx. 100).
    """
    with lock_lecturas:
        datos = list(lecturas_almacenadas)
    return jsonify({
        "status":  "ok",
        "total":   len(datos),
        "lecturas": datos,
    })


@app.route("/api/lecturas/<parcela_id>", methods=["GET"])
def get_lecturas_parcela(parcela_id: str):
    """
    GET /api/lecturas/<parcela_id>
    Retorna lecturas filtradas por el ID de parcela especificado.
    """
    with lock_lecturas:
        filtradas = [
            l for l in lecturas_almacenadas
            if l.get("parcela_id") == parcela_id
        ]
    return jsonify({
        "status":    "ok",
        "parcela_id": parcela_id,
        "total":     len(filtradas),
        "lecturas":  filtradas,
    })


@app.route("/api/status", methods=["GET"])
def get_status():
    """
    GET /api/status
    Retorna el estado general del servicio y métricas de procesamiento.
    """
    with lock_lecturas:
        total_memoria = len(lecturas_almacenadas)
        c_mens   = contador_mensajes
        c_proc   = contador_procesados

    return jsonify({
        "status":               "ok",
        "servicio":             "ingestion_service",
        "mensajes_recibidos":   c_mens,
        "mensajes_procesados":  c_proc,
        "lecturas_en_memoria":  total_memoria,
        "max_registros":        MAX_REGISTROS,
        "broker_mqtt":          f"{MQTT_BROKER_IP}:{MQTT_BROKER_PORT}",
        "timestamp":            datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/ultima-lectura/<parcela_id>", methods=["GET"])
def get_ultima_lectura(parcela_id: str):
    """
    GET /api/ultima-lectura/<parcela_id>
    Retorna la lectura más reciente de una parcela específica.
    """
    with lock_lecturas:
        lecturas_parcela = [
            l for l in lecturas_almacenadas
            if l.get("parcela_id") == parcela_id
        ]

    if not lecturas_parcela:
        return jsonify({
            "status":    "not_found",
            "mensaje":   f"No hay lecturas para la parcela '{parcela_id}'",
            "parcela_id": parcela_id,
        }), 404

    # Las lecturas se agregan en orden cronológico; la última es la más reciente
    ultima = lecturas_parcela[-1]
    return jsonify({
        "status":    "ok",
        "parcela_id": parcela_id,
        "lectura":   ultima,
    })


# ==============================================================================
# PUNTO DE ENTRADA
# ==============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  AGRO-SMART — Servicio de Ingesta y Procesamiento")
    logger.info(f"  Flask escuchando en puerto: {FLASK_PORT}")
    logger.info(f"  Broker MQTT: {MQTT_BROKER_IP}:{MQTT_BROKER_PORT}")
    logger.info("=" * 60)

    # Iniciar cliente MQTT en hilo daemon (no bloquea Flask)
    mqtt_thread = threading.Thread(
        target=iniciar_cliente_mqtt,
        name="mqtt-subscriber",
        daemon=True,
    )
    mqtt_thread.start()
    logger.info("Hilo MQTT iniciado.")

    # Iniciar servidor Flask
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)
