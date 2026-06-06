import os
import sys

from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from .config import Config

socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Enable CORS for all routes
    CORS(app, resources={r"/*": {"origins": "*"}})
    
    socketio_async_mode = os.environ.get("SOCKETIO_ASYNC_MODE")
    if not socketio_async_mode:
        if os.name == "nt" or sys.version_info >= (3, 14):
            socketio_async_mode = "threading"
        else:
            socketio_async_mode = "eventlet"

    # Initialize SocketIO with an async mode that works locally and on Render.
    socketio.init_app(app, cors_allowed_origins="*", async_mode=socketio_async_mode)
    
    # Setup Flask-JWT-Extended
    app.config['JWT_SECRET_KEY'] = 'your-very-secret-key'  # Use a strong secret!
    jwt = JWTManager(app)
    
    # Set secret key and session cookie settings
    app.config['SECRET_KEY'] = Config.SECRET_KEY
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
    
    # Initialize Firebase REST API client
    try:
        from .utils.firebase_rest_api import get_firebase_client
        # Test the client
        client = get_firebase_client()
        print("✅ Firebase REST API client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize Firebase REST API client: {e}")
        # Continue without Firebase - app will still work with limited functionality
    
    # Register blueprints
    from .routes import devices, main, api, auth
    app.register_blueprint(devices.bp, url_prefix='/devices')
    app.register_blueprint(main.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(auth.bp)
    
    # Import WebSocket handlers
    from .routes import websocket_handlers
    
    # Serve Firebase web auth static files
    from flask import send_from_directory

    @app.route('/firebase_auth/web/<path:filename>')
    def firebase_web_auth_static(filename):
        firebase_web_dir = os.path.join(app.root_path, '..', 'firebase_auth', 'web')
        return send_from_directory(firebase_web_dir, filename)

    return app