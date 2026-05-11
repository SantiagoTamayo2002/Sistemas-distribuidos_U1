"""
================================================================================
ARCHIVO: api_gateway.py
ROL EN LA ARQUITECTURA: Componente 4 — API Gateway (Punto de Entrada Único)
================================================================================
DESCRIPCIÓN:
    Este servidor Flask actúa como el único punto de entrada para el dashboard
    y cualquier cliente externo. Enruta las solicitudes hacia los microservicios
    correspondientes (auth_service e ingestion_service), aplicando validación
    de JWT antes de acceder a endpoints protegidos.

    El Gateway abstrae la topología interna de la red: el cliente solo necesita
    conocer la IP del gateway, no las IPs individuales de cada microservicio.

SECCIONES IMPORTANTES:
    - CONFIGURACIÓN: IPs y puertos de cada microservicio (cambiar para red local).
    - proxy_request(): Helper central que reenvía requests HTTP a un microservicio.
    - verificar_jwt_en_gateway(): Valida el token JWT consultando auth_service.
    - POST /gateway/login: Proxy sin autenticación → auth_service.
    - POST /gateway/verify-token: Proxy sin autenticación → auth_service.
    - GET /gateway/lecturas: Requiere JWT válido → proxy a ingestion_service.
    - GET /gateway/lecturas/<id>: Requiere JWT → proxy a ingestion_service.
    - GET /gateway/ultima-lectura/<id>: Requiere JWT → proxy a ingestion_service.
    - GET /gateway/status: Consulta todos los microservicios y retorna estado unificado.

MANEJO DE ERRORES:
    - Si un microservicio está caído, retorna 503 sin crashear el gateway.
    - Si el JWT es inválido o expirado, retorna 401.

DEPENDENCIAS: flask, flask-cors, requests
================================================================================
"""

import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# ==============================================================================
# CONFIGURACIÓN — Editar estas constantes para apuntar a cada PC de la red local
# ==============================================================================
FLASK_PORT = 5000                         # Puerto del API Gateway

# URLs base de cada microservicio (formato: http://<IP>:<puerto>)
AUTH_SERVICE_URL      = "http://localhost:5002"  # PC con auth_service.py
INGESTION_SERVICE_URL = "http://localhost:5001"  # PC con ingestion_service.py

# Timeout en segundos para las llamadas HTTP a los microservicios
REQUEST_TIMEOUT = 10

# ==============================================================================
# LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AgroSmart-Gateway")

# ==============================================================================
# APLICACIÓN FLASK
# ==============================================================================
app = Flask(__name__)
CORS(app, resources={r"/gateway/*": {"origins": "*"}})  # CORS completamente abierto


# ==============================================================================
# HELPERS INTERNOS
# ==============================================================================

def proxy_request(base_url: str, path: str, method: str = "GET",
                  json_body: dict = None, headers: dict = None) -> tuple[dict, int]:
    """
    Reenvía una solicitud HTTP a un microservicio y retorna su respuesta.

    Maneja excepciones de conexión (microservicio caído, timeout) y
    retorna un error 503 estructurado en lugar de propagar la excepción.

    Args:
        base_url:  URL base del microservicio destino.
        path:      Ruta del endpoint (ej. "/api/auth/login").
        method:    Método HTTP ("GET" o "POST").
        json_body: Cuerpo JSON para solicitudes POST (opcional).
        headers:   Headers adicionales a reenviar (opcional).

    Returns:
        Tupla (response_dict, status_code).
    """
    url = f"{base_url}{path}"
    try:
        if method.upper() == "POST":
            resp = requests.post(
                url,
                json=json_body,
                headers=headers or {},
                timeout=REQUEST_TIMEOUT,
            )
        else:
            resp = requests.get(
                url,
                headers=headers or {},
                timeout=REQUEST_TIMEOUT,
            )
        return resp.json(), resp.status_code

    except requests.exceptions.ConnectionError:
        logger.error(f"Microservicio no disponible: {url}")
        return {
            "status":   "error",
            "mensaje":  f"Microservicio no disponible: {base_url}",
            "servicio": base_url,
        }, 503

    except requests.exceptions.Timeout:
        logger.error(f"Timeout al contactar microservicio: {url}")
        return {
            "status":  "error",
            "mensaje": f"Timeout al contactar microservicio: {base_url}",
            "servicio": base_url,
        }, 503

    except Exception as e:
        logger.error(f"Error inesperado al contactar {url}: {e}")
        return {
            "status":  "error",
            "mensaje": f"Error interno del gateway: {str(e)}",
        }, 500


def verificar_jwt_en_gateway() -> tuple[bool, dict, int]:
    """
    Extrae el token JWT del header Authorization y lo valida
    consultando el auth_service (/api/auth/verify).

    Returns:
        Tupla (es_valido: bool, datos_o_error: dict, status_code: int).
        - Si es_valido=True: datos_o_error contiene el payload del token.
        - Si es_valido=False: datos_o_error contiene el mensaje de error,
          y status_code es 401 o 503.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False, {
            "status":  "error",
            "mensaje": "Token de autorización requerido (Bearer <token>)",
        }, 401

    token = auth_header[7:]

    # Delegar la verificación al auth_service
    respuesta, codigo = proxy_request(
        AUTH_SERVICE_URL,
        "/api/auth/verify",
        method="POST",
        json_body={"token": token},
    )

    if codigo != 200:
        return False, respuesta, codigo

    if not respuesta.get("valido", False):
        return False, {
            "status":  "error",
            "mensaje": respuesta.get("mensaje", "Token inválido"),
        }, 401

    return True, respuesta.get("payload", {}), 200


def obtener_status_microservicio(nombre: str, base_url: str, path: str,
                                  resultados: dict, lock: threading.Lock):
    """
    Consulta el endpoint de status de un microservicio y almacena el resultado.
    Diseñado para ejecutarse en un hilo separado.

    Args:
        nombre:     Nombre identificador del microservicio.
        base_url:   URL base del microservicio.
        path:       Ruta del endpoint de status.
        resultados: Diccionario compartido donde guardar el resultado.
        lock:       Mutex para escritura thread-safe en resultados.
    """
    respuesta, codigo = proxy_request(base_url, path)
    with lock:
        resultados[nombre] = {
            "url":      base_url,
            "activo":   codigo == 200,
            "codigo":   codigo,
            "respuesta": respuesta,
        }


# ==============================================================================
# ENDPOINTS DEL GATEWAY
# ==============================================================================

@app.route("/gateway/login", methods=["POST"])
def gateway_login():
    """
    POST /gateway/login
    Proxy hacia auth_service /api/auth/login.
    No requiere autenticación previa.
    """
    body = request.get_json(silent=True) or {}
    logger.info(f"Gateway login para usuario: {body.get('username', 'desconocido')}")

    respuesta, codigo = proxy_request(
        AUTH_SERVICE_URL,
        "/api/auth/login",
        method="POST",
        json_body=body,
    )
    return jsonify(respuesta), codigo


@app.route("/gateway/verify-token", methods=["POST"])
def gateway_verify_token():
    """
    POST /gateway/verify-token
    Proxy hacia auth_service /api/auth/verify.
    No requiere autenticación previa.
    """
    body = request.get_json(silent=True) or {}
    respuesta, codigo = proxy_request(
        AUTH_SERVICE_URL,
        "/api/auth/verify",
        method="POST",
        json_body=body,
    )
    return jsonify(respuesta), codigo


@app.route("/gateway/lecturas", methods=["GET"])
def gateway_lecturas():
    """
    GET /gateway/lecturas
    Requiere token JWT válido en header Authorization: Bearer <token>.
    Proxy hacia ingestion_service /api/lecturas.
    """
    es_valido, payload_o_error, codigo = verificar_jwt_en_gateway()
    if not es_valido:
        return jsonify(payload_o_error), codigo

    logger.info(f"Lecturas solicitadas por: {payload_o_error.get('username')}")
    respuesta, codigo = proxy_request(INGESTION_SERVICE_URL, "/api/lecturas")
    return jsonify(respuesta), codigo


@app.route("/gateway/lecturas/<parcela_id>", methods=["GET"])
def gateway_lecturas_parcela(parcela_id: str):
    """
    GET /gateway/lecturas/<parcela_id>
    Requiere token JWT válido.
    Proxy hacia ingestion_service /api/lecturas/<parcela_id>.
    """
    es_valido, payload_o_error, codigo = verificar_jwt_en_gateway()
    if not es_valido:
        return jsonify(payload_o_error), codigo

    logger.info(
        f"Lecturas de parcela '{parcela_id}' solicitadas por: "
        f"{payload_o_error.get('username')}"
    )
    respuesta, codigo = proxy_request(
        INGESTION_SERVICE_URL, f"/api/lecturas/{parcela_id}"
    )
    return jsonify(respuesta), codigo


@app.route("/gateway/ultima-lectura/<parcela_id>", methods=["GET"])
def gateway_ultima_lectura(parcela_id: str):
    """
    GET /gateway/ultima-lectura/<parcela_id>
    Requiere token JWT válido.
    Proxy hacia ingestion_service /api/ultima-lectura/<parcela_id>.
    """
    es_valido, payload_o_error, codigo = verificar_jwt_en_gateway()
    if not es_valido:
        return jsonify(payload_o_error), codigo

    respuesta, codigo = proxy_request(
        INGESTION_SERVICE_URL, f"/api/ultima-lectura/{parcela_id}"
    )
    return jsonify(respuesta), codigo


@app.route("/gateway/status", methods=["GET"])
def gateway_status():
    """
    GET /gateway/status
    Consulta el endpoint /status de cada microservicio de forma paralela
    (usando hilos) y retorna un JSON consolidado con el estado del sistema.

    Endpoint público — no requiere autenticación.
    Ante microservicios caídos, retorna su estado como inactivo sin crashear.
    """
    resultados = {}
    lock = threading.Lock()

    # Definición de microservicios a consultar
    microservicios = [
        ("auth_service",      AUTH_SERVICE_URL,      "/api/auth/status"),
        ("ingestion_service", INGESTION_SERVICE_URL,  "/api/status"),
    ]

    # Lanzar consultas en paralelo
    hilos = []
    for nombre, url, path in microservicios:
        hilo = threading.Thread(
            target=obtener_status_microservicio,
            args=(nombre, url, path, resultados, lock),
            daemon=True,
        )
        hilos.append(hilo)
        hilo.start()

    # Esperar a que todos los hilos terminen (timeout de REQUEST_TIMEOUT + 1s)
    for hilo in hilos:
        hilo.join(timeout=REQUEST_TIMEOUT + 1)

    # Estado del propio gateway
    resultados["api_gateway"] = {
        "url":    f"http://localhost:{FLASK_PORT}",
        "activo": True,
        "codigo": 200,
        "respuesta": {
            "status":    "ok",
            "servicio":  "api_gateway",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    # Determinar si el sistema está completamente operativo
    todos_activos = all(v.get("activo", False) for v in resultados.values())

    return jsonify({
        "status":         "ok" if todos_activos else "degradado",
        "sistema_activo": todos_activos,
        "microservicios": resultados,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    })


# ==============================================================================
# PUNTO DE ENTRADA
# ==============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  AGRO-SMART — API Gateway")
    logger.info(f"  Gateway escuchando en puerto: {FLASK_PORT}")
    logger.info(f"  Auth Service:      {AUTH_SERVICE_URL}")
    logger.info(f"  Ingestion Service: {INGESTION_SERVICE_URL}")
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)
