"""
Firebase REST API utilities for UniLocator
Replaces Firebase Admin SDK with direct REST API calls for better reliability
"""

import requests
import json
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from google.auth.transport.requests import Request
from google.oauth2 import service_account

# Firebase configuration
FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', 'unilocator-7e8c7')
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)"


def _load_service_account_info():
    """Load Firebase service account info from env JSON or local file."""
    service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
    if service_account_json:
        return json.loads(service_account_json)

    service_account_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'service-account-key.json'
    )

    if os.path.exists(service_account_path):
        with open(service_account_path, 'r', encoding='utf-8') as file_handle:
            return json.load(file_handle)

    return None

class FirebaseRestClient:
    """Firebase REST API client for Firestore operations"""
    
    def __init__(self, project_id: str = None):
        self.project_id = project_id or FIREBASE_PROJECT_ID
        self.base_url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)"
        self.timeout = 10  # 10 second timeout for all requests
        self.access_token = None
        self.token_expiry = None
        self._initialize_auth()
    
    def _initialize_auth(self):
        """Initialize Google Cloud authentication"""
        try:
            service_account_info = _load_service_account_info()

            if service_account_info:
                # Use service account for authentication
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=['https://www.googleapis.com/auth/datastore']
                )
                self.credentials = credentials
                self._refresh_token()
                print("[DEBUG] Service account authentication initialized")
            else:
                print("[DEBUG] Service account key not found in environment or repository")
                self.credentials = None
        except Exception as e:
            print(f"[DEBUG] Failed to initialize authentication: {e}")
            self.credentials = None
    
    def _refresh_token(self):
        """Refresh the access token"""
        if self.credentials:
            try:
                self.credentials.refresh(Request())
                self.access_token = self.credentials.token
                self.token_expiry = self.credentials.expiry
                print("[DEBUG] Access token refreshed")
            except Exception as e:
                print(f"[DEBUG] Failed to refresh token: {e}")
                self.access_token = None
    
    def _get_auth_headers(self):
        """Get authentication headers"""
        if not self.access_token or (self.token_expiry and datetime.now() > self.token_expiry):
            self._refresh_token()
        
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}
    
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make HTTP request with timeout and error handling"""
        kwargs['timeout'] = kwargs.get('timeout', self.timeout)
        
        # Add authentication headers
        headers = kwargs.get('headers', {})
        headers.update(self._get_auth_headers())
        kwargs['headers'] = headers
        
        try:
            response = requests.request(method, url, **kwargs)
            return response
        except requests.exceptions.Timeout:
            logging.error(f"Firebase REST API timeout for {method} {url}")
            raise
        except requests.exceptions.RequestException as e:
            logging.error(f"Firebase REST API error for {method} {url}: {e}")
            raise
    
    def get_document(self, collection: str, document_id: str) -> Optional[Dict]:
        """Get a single document from collection"""
        url = f"{self.base_url}/documents/{collection}/{document_id}"
        try:
            response = self._make_request('GET', url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logging.error(f"Error getting document {collection}/{document_id}: {e}")
            return None
    
    def query_collection(self, collection: str, where_clauses: List[Dict] = None, limit: int = 100) -> List[Dict]:
        """Query collection with optional where clauses"""
        url = f"{self.base_url}/documents:runQuery"
        
        query = {
            "structuredQuery": {
                "from": [{"collectionId": collection}],
                "limit": limit
            }
        }
        
        if where_clauses:
            if len(where_clauses) == 1:
                query["structuredQuery"]["where"] = where_clauses[0]
            else:
                query["structuredQuery"]["where"] = {
                    "compositeFilter": {
                        "op": "AND",
                        "filters": where_clauses
                    }
                }
        
        try:
            print(f"[DEBUG] Querying {collection} with query: {json.dumps(query, indent=2)}")
            response = self._make_request('POST', url, json=query)
            print(f"[DEBUG] Response status: {response.status_code}")
            
            if response.status_code == 200:
                results = response.json()
                print(f"[DEBUG] Raw results: {json.dumps(results, indent=2)[:500]}...")
                documents = []
                for result in results:
                    if "document" in result:
                        documents.append(result["document"])
                print(f"[DEBUG] Found {len(documents)} documents")
                return documents
            else:
                print(f"[DEBUG] Query failed with status {response.status_code}: {response.text}")
            return []
        except Exception as e:
            logging.error(f"Error querying collection {collection}: {e}")
            print(f"[DEBUG] Query exception: {e}")
            return []
    
    def create_document(self, collection: str, document_data: Dict, document_id: str = None) -> Optional[str]:
        """Create a new document in collection"""
        if document_id:
            url = f"{self.base_url}/documents/{collection}/{document_id}"
            method = 'PATCH'
        else:
            url = f"{self.base_url}/documents/{collection}"
            method = 'POST'
        
        # Convert Python dict to Firestore format
        firestore_data = self._convert_to_firestore_format(document_data)
        
        try:
            response = self._make_request(method, url, json={"fields": firestore_data})
            if response.status_code in [200, 201]:
                result = response.json()
                return result.get("name", "").split("/")[-1]  # Extract document ID
            return None
        except Exception as e:
            logging.error(f"Error creating document in {collection}: {e}")
            return None
    
    def update_document(self, collection: str, document_id: str, document_data: Dict) -> bool:
        """Update an existing document"""
        url = f"{self.base_url}/documents/{collection}/{document_id}"
        
        # Convert Python dict to Firestore format
        firestore_data = self._convert_to_firestore_format(document_data)
        
        try:
            response = self._make_request('PATCH', url, json={"fields": firestore_data})
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Error updating document {collection}/{document_id}: {e}")
            return False
    
    def delete_document(self, collection: str, document_id: str) -> bool:
        """Delete a document"""
        url = f"{self.base_url}/documents/{collection}/{document_id}"
        
        try:
            response = self._make_request('DELETE', url)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Error deleting document {collection}/{document_id}: {e}")
            return False
    
    def _convert_to_firestore_format(self, data: Dict) -> Dict:
        """Convert Python dict to Firestore REST API format"""
        result = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = {"stringValue": value}
            elif isinstance(value, int):
                result[key] = {"integerValue": str(value)}
            elif isinstance(value, float):
                result[key] = {"doubleValue": value}
            elif isinstance(value, bool):
                result[key] = {"booleanValue": value}
            elif isinstance(value, dict):
                result[key] = {
                    "mapValue": {
                        "fields": self._convert_to_firestore_format(value)
                    }
                }
            elif isinstance(value, list):
                result[key] = {
                    "arrayValue": {
                        "values": [self._convert_single_value(item) for item in value]
                    }
                }
            elif value is None:
                result[key] = {"nullValue": None}
            else:
                # Default to string
                result[key] = {"stringValue": str(value)}
        
        # Add timestamp for common fields
        current_time = datetime.now().isoformat() + "Z"
        if 'lastSeenAt' in data or 'registeredAt' in data or 'connectedAt' in data:
            if 'lastSeenAt' not in result:
                result['lastSeenAt'] = {"stringValue": current_time}
        
        return result
    
    def _convert_single_value(self, value):
        """Convert a single value to Firestore format"""
        if isinstance(value, str):
            return {"stringValue": value}
        elif isinstance(value, int):
            return {"integerValue": str(value)}
        elif isinstance(value, float):
            return {"doubleValue": value}
        elif isinstance(value, bool):
            return {"booleanValue": value}
        elif isinstance(value, dict):
            return {"mapValue": {"fields": self._convert_to_firestore_format(value)}}
        else:
            return {"stringValue": str(value)}
    
    def _convert_from_firestore_format(self, firestore_data: Dict) -> Dict:
        """Convert Firestore REST API format to Python dict"""
        if "fields" not in firestore_data:
            return {}
        
        result = {}
        fields = firestore_data["fields"]
        
        for key, value_obj in fields.items():
            if "stringValue" in value_obj:
                result[key] = value_obj["stringValue"]
            elif "integerValue" in value_obj:
                result[key] = int(value_obj["integerValue"])
            elif "doubleValue" in value_obj:
                result[key] = value_obj["doubleValue"]
            elif "booleanValue" in value_obj:
                result[key] = value_obj["booleanValue"]
            elif "timestampValue" in value_obj:
                # Handle Firestore timestamp fields
                result[key] = value_obj["timestampValue"]
            elif "mapValue" in value_obj:
                result[key] = self._convert_from_firestore_format({"fields": value_obj["mapValue"].get("fields", {})})
            elif "arrayValue" in value_obj:
                result[key] = [self._convert_single_value_from_firestore(item) for item in value_obj["arrayValue"].get("values", [])]
            elif "nullValue" in value_obj:
                result[key] = None
            else:
                # Debug unknown field types
                print(f"[DEBUG] Unknown field type for {key}: {value_obj}")
        
        return result
    
    def _convert_single_value_from_firestore(self, value_obj):
        """Convert single Firestore value to Python"""
        if "stringValue" in value_obj:
            return value_obj["stringValue"]
        elif "integerValue" in value_obj:
            return int(value_obj["integerValue"])
        elif "doubleValue" in value_obj:
            return value_obj["doubleValue"]
        elif "booleanValue" in value_obj:
            return value_obj["booleanValue"]
        elif "mapValue" in value_obj:
            return self._convert_from_firestore_format({"fields": value_obj["mapValue"].get("fields", {})})
        else:
            return str(value_obj)

# Global client instance
_firebase_client = None

def get_firebase_client() -> FirebaseRestClient:
    """Get Firebase REST API client instance"""
    global _firebase_client
    if _firebase_client is None:
        _firebase_client = FirebaseRestClient()
    return _firebase_client

# Device management functions using REST API
def fetch_user_devices_rest(user_id: str) -> List[Dict]:
    """Fetch user devices using REST API"""
    client = get_firebase_client()
    
    print(f"[DEBUG] fetch_user_devices_rest called for user: {user_id}")
    
    # First try to get all documents to see if the collection exists
    try:
        print("[DEBUG] Trying to fetch all user_devices documents first...")
        all_documents = client.query_collection("user_devices", None, 100)
        print(f"[DEBUG] Found {len(all_documents)} total documents in user_devices collection")
        
        # Print first few document names for debugging
        for i, doc in enumerate(all_documents[:3]):
            doc_name = doc.get("name", "unknown")
            print(f"[DEBUG] Document {i+1}: {doc_name}")
            if "fields" in doc:
                fields = doc["fields"]
                user_field = fields.get("userId", {}).get("stringValue", "no-user-field")
                print(f"[DEBUG]   userId field: {user_field}")
    
    except Exception as e:
        print(f"[DEBUG] Error fetching all documents: {e}")
    
    # Now try with the filter
    where_clauses = [{
        "fieldFilter": {
            "field": {"fieldPath": "userId"},
            "op": "EQUAL",
            "value": {"stringValue": user_id}
        }
    }]
    
    try:
        print(f"[DEBUG] Now trying filtered query for userId: {user_id}")
        documents = client.query_collection("user_devices", where_clauses)
        devices = []
        
        for doc in documents:
            device_data = client._convert_from_firestore_format(doc)
            devices.append(device_data)
        
        logging.info(f"Fetched {len(devices)} devices for user {user_id}")
        return devices
    
    except Exception as e:
        logging.error(f"Error fetching devices for user {user_id}: {e}")
        return []

def create_user_device_rest(user_id: str, device_data: Dict) -> Optional[str]:
    """Create a user device using REST API"""
    client = get_firebase_client()
    
    # Add metadata
    device_data.update({
        'userId': user_id,
        'registeredAt': datetime.now().isoformat() + "Z",
        'lastSeenAt': datetime.now().isoformat() + "Z",
        'isActive': True
    })
    
    try:
        document_id = client.create_document("user_devices", device_data)
        if document_id:
            logging.info(f"Created device {document_id} for user {user_id}")
        return document_id
    
    except Exception as e:
        logging.error(f"Error creating device for user {user_id}: {e}")
        return None

def update_user_device_rest(device_id: str, update_data: Dict) -> bool:
    """Update a user device using REST API"""
    client = get_firebase_client()
    
    # Add last seen timestamp
    update_data['lastSeenAt'] = datetime.now().isoformat() + "Z"
    
    try:
        success = client.update_document("user_devices", device_id, update_data)
        if success:
            logging.info(f"Updated device {device_id}")
        return success
    
    except Exception as e:
        logging.error(f"Error updating device {device_id}: {e}")
        return False

def get_user_device_rest(device_id: str) -> Optional[Dict]:
    """Get a single user device using REST API"""
    client = get_firebase_client()
    
    try:
        doc = client.get_document("user_devices", device_id)
        if doc:
            return client._convert_from_firestore_format(doc)
        return None
    
    except Exception as e:
        logging.error(f"Error getting device {device_id}: {e}")
        return None

def generate_device_code_rest(length: int = 6) -> str:
    """Generate a random device code"""
    import secrets
    import string
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))

def create_device_code_rest(user_id: str) -> Optional[str]:
    """Create a device code using REST API"""
    client = get_firebase_client()
    
    # Generate unique code
    device_code = generate_device_code_rest()
    
    code_data = {
        'code': device_code,
        'userId': user_id,
        'createdAt': datetime.now().isoformat() + "Z",
        'used': False,
        'expiresAt': (datetime.now() + timedelta(hours=1)).isoformat() + "Z"
    }
    
    try:
        document_id = client.create_document("device_codes", code_data)
        if document_id:
            logging.info(f"Created device code {device_code} for user {user_id}")
            return device_code
        return None
    
    except Exception as e:
        logging.error(f"Error creating device code for user {user_id}: {e}")
        return None

# Initialize logging
logging.basicConfig(level=logging.INFO)
