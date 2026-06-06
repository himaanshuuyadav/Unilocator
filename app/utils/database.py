# This file is deprecated - all database operations now use Firebase
# If you see this error, update your code to use firebase_utils instead

def get_db():
    raise NotImplementedError("SQLite database is no longer used. Please use Firebase via firebase_utils.get_firestore_db()")

def close_db(e=None):
    # No-op for Firebase
    pass

def init_db():
    raise NotImplementedError("Database initialization is no longer needed. Firebase is used instead.")

def init_app(app):
    # No-op for Firebase - initialization happens in firebase_utils
    pass