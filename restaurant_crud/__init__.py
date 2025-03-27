
"""
Restaurant CRUD Operations
Functions for creating, reading, updating, and deleting restaurant data.
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
    logging.info('Processing restaurant CRUD operation.')
    
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
        restaurant_container = os.environ.get("RESTAURANT_CONTAINER", "Restaurants")
        
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
        restaurant_collection = database[restaurant_container]
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_restaurant(req, restaurant_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_restaurant(req, restaurant_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_restaurant(req, restaurant_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_restaurant(req, restaurant_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing restaurant operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_restaurant(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Create a new restaurant"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["name"]
        if not all(field in req_body for field in required_fields):
            missing_fields = [field for field in required_fields if field not in req_body]
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Add timestamps and ownership
        current_time = datetime.utcnow().isoformat()
        req_body["created_at"] = current_time
        req_body["updated_at"] = current_time
        req_body["created_by"] = req.token_data.get("preferred_username", "unknown")
        
        # Link to owner if not provided
        if "owner_id" not in req_body:
            req_body["owner_id"] = req.token_data.get("oid", "")
        
        # Set default values if not provided
        if "is_active" not in req_body:
            req_body["is_active"] = True
        
        # Initialize default location structure if not provided
        if "location" not in req_body:
            req_body["location"] = {
                "address": "",
                "city": "",
                "state": "",
                "country": "",
                "postal_code": "",
                "coordinates": {
                    "latitude": 0.0,
                    "longitude": 0.0
                }
            }
        
        # Initialize default contact structure if not provided
        if "contact" not in req_body:
            req_body["contact"] = {
                "phone": "",
                "email": "",
                "website": ""
            }
        
        # Initialize default hours structure if not provided
        if "hours" not in req_body:
            req_body["hours"] = {
                "monday": {"open": "", "close": ""},
                "tuesday": {"open": "", "close": ""},
                "wednesday": {"open": "", "close": ""},
                "thursday": {"open": "", "close": ""},
                "friday": {"open": "", "close": ""},
                "saturday": {"open": "", "close": ""},
                "sunday": {"open": "", "close": ""}
            }
        
        # Initialize empty arrays for relationship fields if not provided
        for field in ["photos", "cuisine_types", "features", "menus", "staff", "qr_codes"]:
            if field not in req_body:
                req_body[field] = []
        
        # Initialize empty object for social media if not provided
        if "social_media" not in req_body:
            req_body["social_media"] = {}
        
        # Set default rating values if not provided
        if "avg_rating" not in req_body:
            req_body["avg_rating"] = 0.0
        if "review_count" not in req_body:
            req_body["review_count"] = 0
        
        # Create the restaurant
        result = collection.insert_one(req_body)
        
        # Get created restaurant with _id
        created_restaurant = collection.find_one({"_id": result.inserted_id})
        
        return func.HttpResponse(
            json.dumps({"message": "Restaurant created successfully", "restaurant": created_restaurant}, cls=JSONEncoder),
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
        logging.error(f"Error creating restaurant: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create restaurant: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_restaurant(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Get restaurant(s) by ID, name, or owner"""
    try:
        # Check for identification parameters
        restaurant_id = req.params.get('id')
        name = req.params.get('name')
        owner_id = req.params.get('owner_id')
        
        # If an ID was provided, get restaurant by ID
        if restaurant_id:
            try:
                restaurant = collection.find_one({"_id": ObjectId(restaurant_id), "is_active": True})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid restaurant ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not restaurant:
                return func.HttpResponse(
                    json.dumps({"error": "Restaurant not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"restaurant": restaurant}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If name was provided, get restaurant by name (exact match)
        elif name:
            restaurant = collection.find_one({"name": name, "is_active": True})
            
            if not restaurant:
                return func.HttpResponse(
                    json.dumps({"error": "Restaurant not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"restaurant": restaurant}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If owner_id was provided, get all restaurants for that owner
        elif owner_id:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Query for restaurants by owner
            restaurants = list(collection.find({"owner_id": owner_id, "is_active": True}).skip(skip).limit(limit))
            total_count = collection.count_documents({"owner_id": owner_id, "is_active": True})
            
            return func.HttpResponse(
                json.dumps({
                    "restaurants": restaurants,
                    "count": len(restaurants),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If no specific identifier, get all restaurants with filtering and pagination
        else:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Get filter parameters
            cuisine_type = req.params.get('cuisine_type')
            city = req.params.get('city')
            search_term = req.params.get('search')
            rating_min = req.params.get('rating_min')
            
            # Build filter query
            query = {"is_active": True}
            
            if cuisine_type:
                query["cuisine_types"] = cuisine_type
            
            if city:
                query["location.city"] = city
            
            if search_term:
                # Text search on name and description
                query["$or"] = [
                    {"name": {"$regex": search_term, "$options": "i"}},
                    {"description": {"$regex": search_term, "$options": "i"}}
                ]
            
            if rating_min:
                query["avg_rating"] = {"$gte": float(rating_min)}
            
            # Execute query with pagination
            restaurants = list(collection.find(query).sort("avg_rating", -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "restaurants": restaurants,
                    "count": len(restaurants),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving restaurant(s): {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve restaurant(s): {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_restaurant(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Update an existing restaurant"""
    try:
        # Get restaurant ID from request
        restaurant_id = req.params.get('id')
        
        if not restaurant_id:
            return func.HttpResponse(
                json.dumps({"error": "Restaurant ID is required for update"}),
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
        
        # Protect created fields
        protected_fields = ["created_at", "created_by"]
        for field in protected_fields:
            if field in req_body:
                del req_body[field]
        
        try:
            # Check if restaurant exists and user is authorized
            existing_restaurant = collection.find_one({"_id": ObjectId(restaurant_id)})
            if not existing_restaurant:
                return func.HttpResponse(
                    json.dumps({"error": "Restaurant not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Verify ownership or admin privileges (if owner_id is in token claims)
            user_id = req.token_data.get("oid", "")
            is_admin = "admin" in req.token_data.get("roles", [])
            is_owner = user_id and user_id == existing_restaurant.get("owner_id")
            
            if not (is_admin or is_owner):
                return func.HttpResponse(
                    json.dumps({"error": "Unauthorized. Only owners or admins can update restaurants"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Update the restaurant
            result = collection.update_one(
                {"_id": ObjectId(restaurant_id)},
                {"$set": req_body}
            )
            
            if result.modified_count > 0:
                # Get updated restaurant
                updated_restaurant = collection.find_one({"_id": ObjectId(restaurant_id)})
                
                return func.HttpResponse(
                    json.dumps({"message": "Restaurant updated successfully", "restaurant": updated_restaurant}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to restaurant"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid restaurant ID format"}),
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
        logging.error(f"Error updating restaurant: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update restaurant: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_restaurant(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Delete (deactivate) a restaurant"""
    try:
        # Get restaurant ID from request
        restaurant_id = req.params.get('id')
        
        if not restaurant_id:
            return func.HttpResponse(
                json.dumps({"error": "Restaurant ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if restaurant exists and user is authorized
            existing_restaurant = collection.find_one({"_id": ObjectId(restaurant_id)})
            if not existing_restaurant:
                return func.HttpResponse(
                    json.dumps({"error": "Restaurant not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Verify ownership or admin privileges (if owner_id is in token claims)
            user_id = req.token_data.get("oid", "")
            is_admin = "admin" in req.token_data.get("roles", [])
            is_owner = user_id and user_id == existing_restaurant.get("owner_id")
            
            if not (is_admin or is_owner):
                return func.HttpResponse(
                    json.dumps({"error": "Unauthorized. Only owners or admins can delete restaurants"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Soft delete (mark as inactive) with user info
            result = collection.update_one(
                {"_id": ObjectId(restaurant_id)},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": datetime.utcnow().isoformat(),
                        "deleted_by": req.token_data.get("preferred_username", "unknown"),
                        "deleted_at": datetime.utcnow().isoformat()
                    }
                }
            )
            
            if result.modified_count > 0:
                return func.HttpResponse(
                    json.dumps({"message": "Restaurant deleted successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "Restaurant was already marked as deleted"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid restaurant ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting restaurant: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete restaurant: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )