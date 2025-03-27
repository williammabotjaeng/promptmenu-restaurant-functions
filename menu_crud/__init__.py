"""
Menu CRUD Operations
Functions for creating, reading, updating, and deleting menu data.
Protected by Entra ID (Azure AD) authentication.
"""

import logging
import json
import azure.functions as func
from pymongo import MongoClient
from bson import ObjectId
import os
from datetime import datetime
import jwt
import requests
from functools import wraps

# Helper function to handle ObjectId serialization
class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(JSONEncoder, self).default(obj)

def validate_token(req):
    """Validate the Entra ID access token from the request"""
    try:
        # Get the auth header
        auth_header = req.headers.get('Authorization')
        if not auth_header:
            return None, "Authorization header is missing"
        
        # Extract the token
        token_parts = auth_header.split()
        if len(token_parts) != 2 or token_parts[0].lower() != 'bearer':
            return None, "Invalid authorization format. Expected 'Bearer {token}'"
        
        token = token_parts[1]
        
        # Get tenant ID from environment
        tenant_id = os.environ.get('AZURE_TENANT_ID')
        if not tenant_id:
            return None, "Tenant ID is not configured"
        
        # Get token validation parameters from environment
        audience = os.environ.get('AZURE_APP_AUDIENCE')
        issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        
        # Get OIDC discovery document to get the signing keys
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        discovery_response = requests.get(discovery_url)
        discovery_data = discovery_response.json()
        jwks_uri = discovery_data['jwks_uri']
        
        # Get the signing keys
        jwks_response = requests.get(jwks_uri)
        jwks_data = jwks_response.json()
        
        # Validate the token
        decoded_token = jwt.decode(
            token,
            jwks_data,
            algorithms=['RS256'],
            audience=audience,
            issuer=issuer,
            options={"verify_signature": True}
        )
        
        return decoded_token, None
    
    except jwt.ExpiredSignatureError:
        return None, "Token has expired"
    except jwt.InvalidTokenError as e:
        return None, f"Invalid token: {str(e)}"
    except Exception as e:
        logging.error(f"Error validating token: {str(e)}")
        return None, f"Error validating token: {str(e)}"

def require_auth(func):
    """Decorator to require authentication for an endpoint"""
    @wraps(func)
    def wrapper(req, collection):
        # Validate the token
        token_data, error = validate_token(req)
        
        if error:
            return func.HttpResponse(
                json.dumps({"error": error, "authenticated": False}),
                status_code=401,
                mimetype="application/json"
            )
        
        # Add the token data to the request for use in the endpoint
        req.token_data = token_data
        
        # Call the original function
        return func(req, collection)
    
    return wrapper

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing menu CRUD operation.')
    
    try:
        # Try to load environment variables
        try:
            from dotenv import load_dotenv
            load_dotenv()
            logging.info("Loaded environment variables from .env file")
        except ImportError:
            logging.info("python-dotenv not installed, using environment variables directly")
        except Exception as e:
            logging.warning(f"Could not load .env file: {str(e)}")
        
        # Load database connection details
        cosmos_db_connection_string = os.environ.get("COSMOS_DB_CONNECTION_STRING")
        database_name = os.environ.get("DATABASE_NAME", "PromptMenuDB")
        menu_container = os.environ.get("MENU_CONTAINER", "Menus")
        
        if not cosmos_db_connection_string:
            return func.HttpResponse(
                json.dumps({"error": "Database connection string is not configured"}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Connect to database
        client = MongoClient(
            cosmos_db_connection_string,
            socketTimeoutMS=30000,
            connectTimeoutMS=30000
        )
        database = client[database_name]
        menu_collection = database[menu_container]
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_menu(req, menu_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_menu(req, menu_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_menu(req, menu_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_menu(req, menu_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing menu operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_menu(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Create a new menu"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["name", "restaurant_id"]
        if not all(field in req_body for field in required_fields):
            missing_fields = [field for field in required_fields if field not in req_body]
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Add timestamps and user info from token
        current_time = datetime.utcnow().isoformat()
        req_body["created_at"] = current_time
        req_body["updated_at"] = current_time
        req_body["created_by"] = req.token_data.get("preferred_username", "unknown")
        
        # Set default values if not provided
        if "is_active" not in req_body:
            req_body["is_active"] = True
        if "categories" not in req_body:
            req_body["categories"] = []
        if "items" not in req_body:
            req_body["items"] = []
        
        # Create the menu
        result = collection.insert_one(req_body)
        
        # Get created menu with _id
        created_menu = collection.find_one({"_id": result.inserted_id})
        
        return func.HttpResponse(
            json.dumps({"message": "Menu created successfully", "menu": created_menu}, cls=JSONEncoder),
            status_code=201,
            mimetype="application/json"
        )
    
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid request body. Please provide valid JSON."}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error creating menu: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create menu: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_menu(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Get menu(s) by ID or restaurant ID"""
    try:
        # Check if an ID was provided
        menu_id = req.params.get('id')
        restaurant_id = req.params.get('restaurant_id')
        
        if menu_id:
            # Get menu by ID
            try:
                menu = collection.find_one({"_id": ObjectId(menu_id)})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid menu ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not menu:
                return func.HttpResponse(
                    json.dumps({"error": "Menu not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"menu": menu}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        elif restaurant_id:
            # Get all menus for a restaurant
            menus = list(collection.find({"restaurant_id": restaurant_id, "is_active": True}))
            
            return func.HttpResponse(
                json.dumps({"menus": menus, "count": len(menus)}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        else:
            # Get all menus (with optional pagination)
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            menus = list(collection.find({"is_active": True}).skip(skip).limit(limit))
            total_count = collection.count_documents({"is_active": True})
            
            return func.HttpResponse(
                json.dumps({
                    "menus": menus,
                    "count": len(menus),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving menu: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve menu: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_menu(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Update an existing menu"""
    try:
        # Get menu ID from request
        menu_id = req.params.get('id')
        
        if not menu_id:
            return func.HttpResponse(
                json.dumps({"error": "Menu ID is required for update"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Add updated timestamp and user info
        req_body["updated_at"] = datetime.utcnow().isoformat()
        req_body["updated_by"] = req.token_data.get("preferred_username", "unknown")
        
        # Remove _id if present (can't update _id)
        if "_id" in req_body:
            del req_body["_id"]
        
        try:
            # Check if menu exists
            existing_menu = collection.find_one({"_id": ObjectId(menu_id)})
            if not existing_menu:
                return func.HttpResponse(
                    json.dumps({"error": "Menu not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Update the menu
            result = collection.update_one(
                {"_id": ObjectId(menu_id)},
                {"$set": req_body}
            )
            
            if result.modified_count > 0:
                # Get updated menu
                updated_menu = collection.find_one({"_id": ObjectId(menu_id)})
                
                return func.HttpResponse(
                    json.dumps({"message": "Menu updated successfully", "menu": updated_menu}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to menu"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid menu ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid request body. Please provide valid JSON."}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Error updating menu: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update menu: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_menu(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Delete (deactivate) a menu"""
    try:
        # Get menu ID from request
        menu_id = req.params.get('id')
        
        if not menu_id:
            return func.HttpResponse(
                json.dumps({"error": "Menu ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if menu exists
            existing_menu = collection.find_one({"_id": ObjectId(menu_id)})
            if not existing_menu:
                return func.HttpResponse(
                    json.dumps({"error": "Menu not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Soft delete (mark as inactive) with user info
            result = collection.update_one(
                {"_id": ObjectId(menu_id)},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.utcnow().isoformat(),
                        "deleted_by": req.token_data.get("preferred_username", "unknown"),
                        "deleted_at": datetime.utcnow().isoformat()
                    }
                }
            )
            
            # For hard delete, use: result = collection.delete_one({"_id": ObjectId(menu_id)})
            
            if result.modified_count > 0:
                return func.HttpResponse(
                    json.dumps({"message": "Menu deleted successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "Menu was already marked as deleted"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid menu ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting menu: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete menu: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )