"""
================================================================================
ARCHIVO: iot_simulator.py
ROL EN LA ARQUITECTURA: Componente 1 — Simulador de Nodos IoT con MQTT
================================================================================
DESCRIPCIÓN:
    Este script simula el comportamiento de múltiples nodos IoT de campo que
    envían datos de sensores agrícolas al broker MQTT (Mosquitto). Es el punto
    de origen de todos los datos en el sistema Agro-Smart.

    Cada nodo IoT simulado representa un dispositivo físico instalado en una
    parcela agrícola, equipado con sensores de humedad de suelo, temperatura,
    humedad del aire, nivel de batería y señal de red (RSSI).

SECCIONES IMPORTANTES:
    - CONFIGURACIÓN: Constantes configurables al inicio del archivo.
    - NODOS_IOT: Definición de los nodos a simular (parcelas y IDs).
    - generar_telemetria(): Genera datos de sensor con valores aleatorios realistas.
    - publicar_telemetria(): Conecta al broker y publica mensajes periódicamente.
    - on_connect / on_disconnect: Callbacks del cliente MQTT para gestión de conexión.
    - main(): Lanza un hilo por nodo de forma concurrente.

PROTOCOLO: MQTT (publish al topic agrosmart/{parcela_id}/{nodo_id}/telemetry)
DEPENDENCIAS: paho-mqtt
================================================================================
"""

import json
import time
import random
import threading
import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# ==============================================================================
# CONFIGURACIÓN — Editar estas constantes para apuntar al broker correcto
# ==============================================================================
MQTT_BROKER_IP   = "localhost"   # IP del broker Mosquitto (cambiar para red local)
MQTT_BROKER_PORT = 1883          # Puerto estándar de Mosquitto
MQTT_KEEPALIVE   = 60            # Segundos de keepalive
INTERVALO_PUBLICACION = 30       # Segundos entre publicaciones por nodo
MQTT_RECONNECT_DELAY  = 5        # Segundos entre intentos de reconexión

# ==============================================================================
# DEFINICIÓN DE NODOS IOT A SIMULAR
# Cada entrada representa un dispositivo físico con su parcela y nodo únicos.
# ==============================================================================
NODOS_IOT = [
    {"parcela_id": "parcela_01", "nodo_id": "nodo_A1"},
    {"parcela_id": "parcela_01", "nodo_id": "nodo_A2"},
]

# ==============================================================================
# CONFIGURACIÓN DE LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AgroSmart-IoT")


# ==============================================================================
# GENERACIÓN DE TELEMETRÍA
# ==============================================================================

def generar_telemetria(parcela_id: str, nodo_id: str) -> dict:
    """
    Genera un payload JSON con valores de sensores dentro de rangos realistas.

    Rangos utilizados:
        - humedad_suelo: 20–80 %   (porcentaje de humedad volumétrica del suelo)
        - temperatura:   15–35 °C  (temperatura ambiental típica de campo)
        - humedad_aire:  40–90 %   (humedad relativa del ambiente)
        - bateria_pct:   10–100 %  (nivel de batería del nodo)
        - rssi:         -90 a -40 dBm (intensidad de señal WiFi/LoRa)

    Args:
        parcela_id: Identificador de la parcela.
        nodo_id:    Identificador del nodo dentro de la parcela.

    Returns:
        dict con todos los campos de telemetría.
    """
    return {
        "parcela_id":    parcela_id,
        "nodo_id":       nodo_id,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "humedad_suelo": round(random.uniform(20.0, 80.0), 2),
        "temperatura":   round(random.uniform(15.0, 35.0), 2),
        "humedad_aire":  round(random.uniform(40.0, 90.0), 2),
        "rssi":          round(random.uniform(-90.0, -40.0), 1),
    }


# ==============================================================================
# CALLBACKS MQTT
# ==============================================================================

def on_connect(client, userdata, flags, rc):
    """Callback ejecutado cuando el cliente MQTT se conecta al broker."""
    nodo_info = userdata  # userdata contiene {"parcela_id": ..., "nodo_id": ...}
    if rc == 0:
        logger.info(
            f"[{nodo_info['nodo_id']}] Conectado al broker MQTT "
            f"{MQTT_BROKER_IP}:{MQTT_BROKER_PORT}"
        )
    else:
        logger.warning(
            f"[{nodo_info['nodo_id']}] Fallo de conexión al broker, código: {rc}"
        )


def on_disconnect(client, userdata, rc):
    """Callback ejecutado cuando el cliente MQTT se desconecta del broker."""
    nodo_info = userdata
    if rc != 0:
        logger.warning(
            f"[{nodo_info['nodo_id']}] Desconexión inesperada (código {rc}). "
            f"Reconectando en {MQTT_RECONNECT_DELAY}s..."
        )


def on_publish(client, userdata, mid):
    """Callback ejecutado cuando un mensaje es confirmado como publicado."""
    pass  # Confirmación silenciosa; el log principal está en publicar_telemetria


# ==============================================================================
# FUNCIÓN PRINCIPAL DEL NODO
# ==============================================================================

def publicar_telemetria(parcela_id: str, nodo_id: str):
    """
    Ciclo de vida de un nodo IoT simulado.

    Crea un cliente MQTT, se conecta al broker con reconexión automática,
    y publica telemetría cada INTERVALO_PUBLICACION segundos de forma indefinida.

    El topic de publicación sigue el esquema:
        agrosmart/{parcela_id}/{nodo_id}/telemetry

    Args:
        parcela_id: Identificador de la parcela del nodo.
        nodo_id:    Identificador único del nodo.
    """
    nodo_info = {"parcela_id": parcela_id, "nodo_id": nodo_id}
    topic = f"agrosmart/{parcela_id}/{nodo_id}/telemetry"

    # Crear cliente MQTT con ID único para evitar colisiones en el broker
    client_id = f"agrosmart-sim-{nodo_id}-{int(time.time())}"
    client = mqtt.Client(client_id=client_id, userdata=nodo_info)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish    = on_publish

    # Habilitar reconexión automática exponencial (2s a 120s)
    client.reconnect_delay_set(min_delay=2, max_delay=120)

    # Intentar conexión inicial con reintentos
    while True:
        try:
            logger.info(f"[{nodo_id}] Intentando conectar al broker {MQTT_BROKER_IP}:{MQTT_BROKER_PORT}...")
            client.connect(MQTT_BROKER_IP, MQTT_BROKER_PORT, MQTT_KEEPALIVE)
            break
        except Exception as e:
            logger.error(
                f"[{nodo_id}] No se pudo conectar al broker: {e}. "
                f"Reintentando en {MQTT_RECONNECT_DELAY}s..."
            )
            time.sleep(MQTT_RECONNECT_DELAY)

    # Iniciar loop de red de MQTT en segundo plano
    client.loop_start()

    # Ciclo de publicación
    try:
        while True:
            telemetria = generar_telemetria(parcela_id, nodo_id)
            payload    = json.dumps(telemetria)

            resultado = client.publish(topic, payload, qos=1)

            if resultado.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(
                    f"[{nodo_id}] PUBLICADO → {topic} | "
                    f"Humedad suelo: {telemetria['humedad_suelo']}% | "
                    f"Temp: {telemetria['temperatura']}°C | "
                )
            else:
                logger.warning(f"[{nodo_id}] Error al publicar (código {resultado.rc})")

            time.sleep(INTERVALO_PUBLICACION)

    except KeyboardInterrupt:
        logger.info(f"[{nodo_id}] Deteniendo nodo por señal de interrupción.")
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info(f"[{nodo_id}] Nodo desconectado.")


# ==============================================================================
# PUNTO DE ENTRADA PRINCIPAL
# ==============================================================================

def main():
    """
    Lanza un hilo de simulación por cada nodo IoT definido en NODOS_IOT.
    Todos los nodos operan de forma concurrente e independiente.
    """
    logger.info("=" * 60)
    logger.info("  AGRO-SMART — Simulador de Nodos IoT")
    logger.info(f"  Broker MQTT: {MQTT_BROKER_IP}:{MQTT_BROKER_PORT}")
    logger.info(f"  Nodos a simular: {len(NODOS_IOT)}")
    logger.info(f"  Intervalo de publicación: {INTERVALO_PUBLICACION}s")
    logger.info("=" * 60)

    hilos = []
    for nodo in NODOS_IOT:
        hilo = threading.Thread(
            target=publicar_telemetria,
            args=(nodo["parcela_id"], nodo["nodo_id"]),
            name=f"nodo-{nodo['nodo_id']}",
            daemon=True,
        )
        hilos.append(hilo)
        hilo.start()
        logger.info(f"Nodo iniciado: {nodo['parcela_id']}/{nodo['nodo_id']}")
        time.sleep(0.5)  # Pequeño delay para escalonar conexiones al broker

    logger.info("Todos los nodos iniciados. Presiona Ctrl+C para detener.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Simulador detenido por el usuario.")


if __name__ == "__main__":
    main()
