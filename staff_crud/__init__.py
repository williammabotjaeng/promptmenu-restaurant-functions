"""
Staff CRUD Operations
Functions for creating, reading, updating, and deleting staff data.
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
    def wrapper(req, collection, *args, **kwargs):
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
        return func(req, collection, *args, **kwargs)
    
    return wrapper

def has_restaurant_access(req, restaurant_id, restaurant_collection):
    """Check if user has access to the restaurant"""
    try:
        # Get the restaurant
        restaurant = restaurant_collection.find_one({"_id": ObjectId(restaurant_id)})
        if not restaurant:
            return False, "Restaurant not found"
        
        # Check if user is the owner or admin
        user_id = req.token_data.get("oid", "")
        is_admin = "admin" in req.token_data.get("roles", [])
        is_owner = user_id and user_id == restaurant.get("owner_id")
        
        if not (is_admin or is_owner):
            return False, "Unauthorized. Only restaurant owners or admins can manage staff"
        
        return True, None
    except Exception as e:
        logging.error(f"Error checking restaurant access: {str(e)}")
        return False, f"Error checking restaurant access: {str(e)}"

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing staff CRUD operation.')
    
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
        staff_container = os.environ.get("STAFF_CONTAINER", "Staff")
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
        staff_collection = database[staff_container]
        restaurant_collection = database[restaurant_container]
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_staff(req, staff_collection, restaurant_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_staff(req, staff_collection, restaurant_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_staff(req, staff_collection, restaurant_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_staff(req, staff_collection, restaurant_collection)
        elif req.method == 'PUT' and operation.lower() == 'feature':
            return feature_staff(req, staff_collection, restaurant_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing staff operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_staff(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Create a new staff member"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["restaurant_id", "name", "position"]
        if not all(field in req_body for field in required_fields):
            missing_fields = [field for field in required_fields if field not in req_body]
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Check restaurant access
        restaurant_id = req_body["restaurant_id"]
        has_access, error_msg = has_restaurant_access(req, restaurant_id, restaurant_collection)
        if not has_access:
            return func.HttpResponse(
                json.dumps({"error": error_msg}),
                status_code=403,
                mimetype="application/json"
            )
        
        # Add timestamps
        current_time = datetime.utcnow().isoformat()
        req_body["created_at"] = current_time
        req_body["updated_at"] = current_time
        req_body["created_by"] = req.token_data.get("preferred_username", "unknown")
        
        # Set default values if not provided
        if "is_active" not in req_body:
            req_body["is_active"] = True
        if "featured" not in req_body:
            req_body["featured"] = False
        
        # Initialize empty arrays for collection fields
        for field in ["videos", "photos", "menu_items", "specialties", "awards"]:
            if field not in req_body:
                req_body[field] = []
        
        # Initialize empty objects
        if "social_media" not in req_body:
            req_body["social_media"] = {}
        
        # Create the staff member
        result = collection.insert_one(req_body)
        
        # Get created staff with _id
        created_staff = collection.find_one({"_id": result.inserted_id})
        
        # Update restaurant staff array if not already in it
        staff_id = str(result.inserted_id)
        restaurant_collection.update_one(
            {"_id": ObjectId(restaurant_id), "staff": {"$ne": staff_id}},
            {"$push": {"staff": staff_id}}
        )
        
        return func.HttpResponse(
            json.dumps({"message": "Staff member created successfully", "staff": created_staff}, cls=JSONEncoder),
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
        logging.error(f"Error creating staff: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create staff: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_staff(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Get staff member(s) by ID or restaurant ID"""
    try:
        # Check for identification parameters
        staff_id = req.params.get('id')
        restaurant_id = req.params.get('restaurant_id')
        
        # If an ID was provided, get staff by ID
        if staff_id:
            try:
                staff = collection.find_one({"_id": ObjectId(staff_id), "is_active": True})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid staff ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not staff:
                return func.HttpResponse(
                    json.dumps({"error": "Staff member not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"staff": staff}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If restaurant ID was provided, get all staff for that restaurant
        elif restaurant_id:
            # Check if user has access to view all staff (if admin, no check needed)
            is_admin = "admin" in req.token_data.get("roles", [])
            if not is_admin:
                # For non-admins, verify they have access to the restaurant
                has_access, error_msg = has_restaurant_access(req, restaurant_id, restaurant_collection)
                if not has_access and req.params.get('include_private', 'false').lower() == 'true':
                    return func.HttpResponse(
                        json.dumps({"error": error_msg}),
                        status_code=403,
                        mimetype="application/json"
                    )
            
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Get filter parameters
            include_private = req.params.get('include_private', 'false').lower() == 'true'
            position = req.params.get('position')
            featured_only = req.params.get('featured_only', 'false').lower() == 'true'
            
            # Build query
            query = {"restaurant_id": restaurant_id, "is_active": True}
            
            # Only include featured staff for public view
            if featured_only or not include_private:
                query["featured"] = True
            
            if position:
                query["position"] = position
            
            # Get staff members with pagination
            staff_members = list(collection.find(query).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "staff": staff_members,
                    "count": len(staff_members),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If no parameters, return error
        else:
            return func.HttpResponse(
                json.dumps({"error": "Either staff ID or restaurant ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving staff: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve staff: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_staff(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Update an existing staff member"""
    try:
        # Get staff ID from request
        staff_id = req.params.get('id')
        
        if not staff_id:
            return func.HttpResponse(
                json.dumps({"error": "Staff ID is required for update"}),
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
        
        # Don't allow direct updates to certain fields
        protected_fields = ["created_at", "created_by", "restaurant_id"]
        for field in protected_fields:
            if field in req_body:
                del req_body[field]
        
        try:
            # Check if staff exists
            existing_staff = collection.find_one({"_id": ObjectId(staff_id)})
            if not existing_staff:
                return func.HttpResponse(
                    json.dumps({"error": "Staff member not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Check restaurant access
            restaurant_id = existing_staff["restaurant_id"]
            has_access, error_msg = has_restaurant_access(req, restaurant_id, restaurant_collection)
            if not has_access:
                return func.HttpResponse(
                    json.dumps({"error": error_msg}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Update the staff member
            result = collection.update_one(
                {"_id": ObjectId(staff_id)},
                {"$set": req_body}
            )
            
            if result.modified_count > 0:
                # Get updated staff
                updated_staff = collection.find_one({"_id": ObjectId(staff_id)})
                
                return func.HttpResponse(
                    json.dumps({"message": "Staff member updated successfully", "staff": updated_staff}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to staff member"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid staff ID format"}),
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
        logging.error(f"Error updating staff: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update staff: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_staff(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Delete (deactivate) a staff member"""
    try:
        # Get staff ID from request
        staff_id = req.params.get('id')
        
        if not staff_id:
            return func.HttpResponse(
                json.dumps({"error": "Staff ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if staff exists
            existing_staff = collection.find_one({"_id": ObjectId(staff_id)})
            if not existing_staff:
                return func.HttpResponse(
                    json.dumps({"error": "Staff member not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Check restaurant access
            restaurant_id = existing_staff["restaurant_id"]
            has_access, error_msg = has_restaurant_access(req, restaurant_id, restaurant_collection)
            if not has_access:
                return func.HttpResponse(
                    json.dumps({"error": error_msg}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Soft delete (mark as inactive) with user info
            result = collection.update_one(
                {"_id": ObjectId(staff_id)},
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
                # Remove from restaurant staff array
                restaurant_collection.update_one(
                    {"_id": ObjectId(restaurant_id)},
                    {"$pull": {"staff": staff_id}}
                )
                
                return func.HttpResponse(
                    json.dumps({"message": "Staff member deleted successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "Staff member was already marked as deleted"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid staff ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting staff: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete staff: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def feature_staff(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Feature or unfeature a staff member"""
    try:
        # Get staff ID from request
        staff_id = req.params.get('id')
        
        if not staff_id:
            return func.HttpResponse(
                json.dumps({"error": "Staff ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get featured status from request
        req_body = req.get_json()
        featured = req_body.get("featured", True)
        
        try:
            # Check if staff exists
            existing_staff = collection.find_one({"_id": ObjectId(staff_id)})
            if not existing_staff:
                return func.HttpResponse(
                    json.dumps({"error": "Staff member not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Check restaurant access
            restaurant_id = existing_staff["restaurant_id"]
            has_access, error_msg = has_restaurant_access(req, restaurant_id, restaurant_collection)
            if not has_access:
                return func.HttpResponse(
                    json.dumps({"error": error_msg}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Update featured status
            result = collection.update_one(
                {"_id": ObjectId(staff_id)},
                {
                    "$set": {
                        "featured": featured,
                        "updated_at": datetime.utcnow().isoformat(),
                        "updated_by": req.token_data.get("preferred_username", "unknown")
                    }
                }
            )
            
            if result.modified_count > 0:
                # Get updated staff
                updated_staff = collection.find_one({"_id": ObjectId(staff_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": f"Staff member {'featured' if featured else 'unfeatured'} successfully", 
                        "staff": updated_staff
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to staff member"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid staff ID format"}),
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
        logging.error(f"Error featuring staff: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to feature staff: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )