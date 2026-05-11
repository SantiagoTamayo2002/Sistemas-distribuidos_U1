"""
================================================================================
ARCHIVO: auth_service.py
ROL EN LA ARQUITECTURA: Componente 3 — Servicio de Autenticación
================================================================================
DESCRIPCIÓN:
    Este servidor Flask gestiona la autenticación de usuarios del sistema
    Agro-Smart mediante usuario/contraseña y tokens JWT (JSON Web Tokens).

    Los usuarios están precargados en memoria (sin base de datos) con
    contraseñas almacenadas como hash SHA-256. Los JWT firmados contienen
    el username, rol y parcelas asignadas del usuario, con expiración de 2 horas.

SECCIONES IMPORTANTES:
    - CONFIGURACIÓN: SECRET_KEY y puerto configurable al inicio del archivo.
    - USUARIOS_BD: Diccionario en memoria con usuarios precargados.
    - hashear_password(): Genera hash SHA-256 de una contraseña.
    - POST /api/auth/login: Valida credenciales y emite JWT.
    - POST /api/auth/verify: Verifica y decodifica un JWT.
    - GET /api/auth/usuarios: Lista usuarios (solo para admin con JWT válido).
    - GET /api/auth/status: Health check público del servicio.
    - verificar_token_admin(): Decorador/helper para proteger rutas de admin.

SEGURIDAD:
    - Contraseñas hasheadas con SHA-256 (no almacenadas en texto plano).
    - Tokens JWT firmados con HS256 y expiración de 2 horas.
    - CORS completamente abierto para comunicación entre PCs de la red.
DEPENDENCIAS: flask, flask-cors, PyJWT
================================================================================
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS

# ==============================================================================
# CONFIGURACIÓN — Editar estas constantes según el entorno
# ==============================================================================
FLASK_PORT      = 5002                              # Puerto del servidor Flask
SECRET_KEY      = "agrosmart-secret-key-2024-!$#"  # Clave secreta para firmar JWT
JWT_EXPIRACION_HORAS = 2                            # Horas de validez del token
ALGORITHM       = "HS256"                           # Algoritmo de firma JWT

# ==============================================================================
# LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AgroSmart-Auth")


# ==============================================================================
# FUNCIONES DE UTILIDAD
# ==============================================================================

def hashear_password(password: str) -> str:
    """
    Genera el hash SHA-256 de una contraseña en texto plano.

    Args:
        password: Contraseña en texto plano.

    Returns:
        str con el hash hexadecimal SHA-256.
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ==============================================================================
# BASE DE DATOS DE USUARIOS EN MEMORIA
# Las contraseñas se almacenan como hash SHA-256, nunca en texto plano.
# Para agregar usuarios: añadir entradas con "password": hashear_password("tu_pass")
# ==============================================================================
USUARIOS_BD = {
    "admin": {
        "username":          "admin",
        "password":          hashear_password("admin123"),   # Hash de "admin123"
        "rol":               "admin",
        "nombre_completo":   "Administrador del Sistema",
        "parcelas_asignadas": ["parcela_01", "parcela_02", "parcela_03"],
    },
    "juan_agricultor": {
        "username":          "juan_agricultor",
        "password":          hashear_password("campo2024"),  # Hash de "campo2024"
        "rol":               "agricultor",
        "nombre_completo":   "Juan Carlos Mendoza",
        "parcelas_asignadas": ["parcela_01", "parcela_02"],
    },
    "maria_supervisora": {
        "username":          "maria_supervisora",
        "password":          hashear_password("riego#456"),  # Hash de "riego#456"
        "rol":               "agricultor",
        "nombre_completo":   "María Elena Rodríguez",
        "parcelas_asignadas": ["parcela_03"],
    },
}

logger.info(f"Base de datos de usuarios cargada: {len(USUARIOS_BD)} usuarios registrados.")


# ==============================================================================
# APLICACIÓN FLASK
# ==============================================================================
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # CORS completamente abierto


# ==============================================================================
# HELPERS DE AUTENTICACIÓN
# ==============================================================================

def generar_jwt(usuario: dict) -> str:
    """
    Genera un token JWT firmado para un usuario autenticado.

    El payload incluye:
        - username: nombre de usuario
        - rol: rol del usuario en el sistema
        - parcelas_asignadas: lista de parcelas accesibles
        - exp: tiempo de expiración (ahora + JWT_EXPIRACION_HORAS)
        - iat: tiempo de emisión (issued at)

    Args:
        usuario: Diccionario del usuario desde USUARIOS_BD.

    Returns:
        str con el token JWT codificado.
    """
    payload = {
        "username":          usuario["username"],
        "rol":               usuario["rol"],
        "nombre_completo":   usuario["nombre_completo"],
        "parcelas_asignadas": usuario["parcelas_asignadas"],
        "iat":               datetime.now(timezone.utc),
        "exp":               datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRACION_HORAS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_jwt(token: str) -> tuple[bool, dict | str]:
    """
    Decodifica y valida un token JWT.

    Args:
        token: Token JWT como string.

    Returns:
        Tupla (es_valido: bool, datos_o_error: dict | str).
        Si es_valido=True, retorna el payload decodificado.
        Si es_valido=False, retorna el mensaje de error.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True, payload
    except jwt.ExpiredSignatureError:
        return False, "Token expirado"
    except jwt.InvalidTokenError as e:
        return False, f"Token inválido: {str(e)}"


def obtener_token_del_header() -> str | None:
    """
    Extrae el token JWT del header Authorization en formato 'Bearer <token>'.

    Returns:
        str con el token, o None si no está presente o mal formateado.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]  # Eliminar el prefijo "Bearer "
    return None


# ==============================================================================
# ENDPOINTS
# ==============================================================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    """
    POST /api/auth/login
    Autentica un usuario con username y password.

    Body JSON esperado:
        {"username": "...", "password": "..."}

    Respuesta exitosa:
        {"status": "ok", "token": "<JWT>", "usuario": {...}}

    Respuesta de error:
        {"status": "error", "mensaje": "..."} con código 401
    """
    datos = request.get_json(silent=True)
    if not datos:
        return jsonify({"status": "error", "mensaje": "Body JSON requerido"}), 400

    username = datos.get("username", "").strip()
    password = datos.get("password", "")

    if not username or not password:
        return jsonify({
            "status":  "error",
            "mensaje": "username y password son requeridos",
        }), 400

    # Buscar usuario en la "base de datos"
    usuario = USUARIOS_BD.get(username)
    if not usuario:
        logger.warning(f"Intento de login con usuario inexistente: '{username}'")
        return jsonify({
            "status":  "error",
            "mensaje": "Credenciales inválidas",
        }), 401

    # Verificar contraseña (comparar hashes)
    if usuario["password"] != hashear_password(password):
        logger.warning(f"Contraseña incorrecta para usuario: '{username}'")
        return jsonify({
            "status":  "error",
            "mensaje": "Credenciales inválidas",
        }), 401

    # Generar token JWT
    token = generar_jwt(usuario)
    logger.info(f"Login exitoso: {username} (rol: {usuario['rol']})")

    return jsonify({
        "status": "ok",
        "token":  token,
        "usuario": {
            "username":          usuario["username"],
            "nombre_completo":   usuario["nombre_completo"],
            "rol":               usuario["rol"],
            "parcelas_asignadas": usuario["parcelas_asignadas"],
        },
        "expira_en_horas": JWT_EXPIRACION_HORAS,
    })


@app.route("/api/auth/verify", methods=["POST"])
def verify_token():
    """
    POST /api/auth/verify
    Verifica si un token JWT es válido y retorna sus datos decodificados.

    Body JSON esperado:
        {"token": "<JWT>"}

    Respuesta válida:
        {"status": "ok", "valido": true, "payload": {...}}

    Respuesta inválida:
        {"status": "ok", "valido": false, "mensaje": "..."}
    """
    datos = request.get_json(silent=True)
    if not datos or "token" not in datos:
        return jsonify({"status": "error", "mensaje": "Campo 'token' requerido"}), 400

    token = datos["token"]
    es_valido, resultado = decodificar_jwt(token)

    if es_valido:
        return jsonify({
            "status":  "ok",
            "valido":  True,
            "payload": resultado,
        })
    else:
        return jsonify({
            "status":  "ok",
            "valido":  False,
            "mensaje": resultado,
        })


@app.route("/api/auth/usuarios", methods=["GET"])
def get_usuarios():
    """
    GET /api/auth/usuarios
    Retorna la lista de usuarios (sin contraseñas).
    Requiere token JWT de rol 'admin' en el header Authorization: Bearer <token>.

    Respuesta exitosa:
        {"status": "ok", "usuarios": [...]}

    Respuesta de error:
        {"status": "error", "mensaje": "..."} con código 401 o 403
    """
    token = obtener_token_del_header()
    if not token:
        return jsonify({
            "status":  "error",
            "mensaje": "Token de autorización requerido (Bearer <token>)",
        }), 401

    es_valido, resultado = decodificar_jwt(token)
    if not es_valido:
        return jsonify({"status": "error", "mensaje": resultado}), 401

    # Verificar rol de administrador
    if resultado.get("rol") != "admin":
        return jsonify({
            "status":  "error",
            "mensaje": "Acceso denegado: se requiere rol 'admin'",
        }), 403

    # Retornar usuarios sin contraseñas
    usuarios_sin_pass = [
        {
            "username":          u["username"],
            "nombre_completo":   u["nombre_completo"],
            "rol":               u["rol"],
            "parcelas_asignadas": u["parcelas_asignadas"],
        }
        for u in USUARIOS_BD.values()
    ]

    return jsonify({
        "status":   "ok",
        "total":    len(usuarios_sin_pass),
        "usuarios": usuarios_sin_pass,
    })


@app.route("/api/auth/status", methods=["GET"])
def get_status():
    """
    GET /api/auth/status
    Endpoint público de health check del servicio de autenticación.
    No requiere autenticación.
    """
    return jsonify({
        "status":         "ok",
        "servicio":       "auth_service",
        "usuarios_total": len(USUARIOS_BD),
        "algoritmo_jwt":  ALGORITHM,
        "expiracion_jwt": f"{JWT_EXPIRACION_HORAS} horas",
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    })


# ==============================================================================
# PUNTO DE ENTRADA
# ==============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  AGRO-SMART — Servicio de Autenticación")
    logger.info(f"  Flask escuchando en puerto: {FLASK_PORT}")
    logger.info(f"  Usuarios precargados: {list(USUARIOS_BD.keys())}")
    logger.info("=" * 60)
    logger.info("  Credenciales de prueba:")
    logger.info("    admin          / admin123")
    logger.info("    juan_agricultor / campo2024")
    logger.info("    maria_supervisora / riego#456")
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)
