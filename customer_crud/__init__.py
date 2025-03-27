"""
Customer CRUD Operations
Functions for creating, reading, updating, and deleting customer data.
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
    logging.info('Processing customer CRUD operation.')
    
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
        customer_container = os.environ.get("CUSTOMER_CONTAINER", "Customers")
        
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
        customer_collection = database[customer_container]
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_customer(req, customer_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_customer(req, customer_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_customer(req, customer_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_customer(req, customer_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing customer operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_customer(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Create a new customer"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["fullname", "email"]
        if not all(field in req_body for field in required_fields):
            missing_fields = [field for field in required_fields if field not in req_body]
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Add timestamps
        current_time = datetime.utcnow().isoformat()
        req_body["created_at"] = current_time
        req_body["updated_at"] = current_time
        req_body["created_by"] = req.token_data.get("preferred_username", "unknown")
        
        # If the customer is created through Entra ID, link their identity
        if 'entra_id' not in req_body and 'oid' in req.token_data:
            req_body["entra_id"] = req.token_data.get("oid")
            req_body["user_principal_name"] = req.token_data.get("preferred_username")
        
        # Set default values if not provided
        if "is_active" not in req_body:
            req_body["is_active"] = True
        if "loyalty_points" not in req_body:
            req_body["loyalty_points"] = 0
        if "loyalty_tier" not in req_body:
            req_body["loyalty_tier"] = "Standard"
        if "visit_count" not in req_body:
            req_body["visit_count"] = 0
        
        # Initialize empty arrays and objects for relationship fields
        for field in ["dietary_preferences", "allergens", "favorite_restaurants", 
                     "favorite_dishes", "cuisine_preferences", "order_history", 
                     "reservations", "payment_methods", "tags"]:
            if field not in req_body:
                req_body[field] = []
        
        # Initialize nested objects
        if "address" not in req_body:
            req_body["address"] = {
                "street": "",
                "city": "",
                "state": "",
                "country": "",
                "postal_code": ""
            }
        
        if "marketing_preferences" not in req_body:
            req_body["marketing_preferences"] = {
                "email": False,
                "sms": False,
                "push": False
            }
        
        if "custom_fields" not in req_body:
            req_body["custom_fields"] = {}
        
        # Create the customer
        result = collection.insert_one(req_body)
        
        # Get created customer with _id
        created_customer = collection.find_one({"_id": result.inserted_id})
        
        # Remove sensitive information before returning
        if "password" in created_customer:
            del created_customer["password"]
        
        return func.HttpResponse(
            json.dumps({"message": "Customer created successfully", "customer": created_customer}, cls=JSONEncoder),
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
        logging.error(f"Error creating customer: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create customer: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_customer(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Get customer(s) by ID, email, or entra_id"""
    try:
        # Check for identification parameters
        customer_id = req.params.get('id')
        email = req.params.get('email')
        entra_id = req.params.get('entra_id')
        phone = req.params.get('phone_number')
        
        # If an ID was provided, get customer by ID
        if customer_id:
            try:
                customer = collection.find_one({"_id": ObjectId(customer_id), "is_active": True})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid customer ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Remove sensitive information
            if "password" in customer:
                del customer["password"]
            
            return func.HttpResponse(
                json.dumps({"customer": customer}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If email was provided, get customer by email
        elif email:
            customer = collection.find_one({"email": email, "is_active": True})
            
            if not customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Remove sensitive information
            if "password" in customer:
                del customer["password"]
            
            return func.HttpResponse(
                json.dumps({"customer": customer}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If entra_id was provided, get customer by entra_id
        elif entra_id:
            customer = collection.find_one({"entra_id": entra_id, "is_active": True})
            
            if not customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Remove sensitive information
            if "password" in customer:
                del customer["password"]
            
            return func.HttpResponse(
                json.dumps({"customer": customer}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
            
        # If phone number was provided, get customer by phone
        elif phone:
            customer = collection.find_one({"phone_number": phone, "is_active": True})
            
            if not customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Remove sensitive information
            if "password" in customer:
                del customer["password"]
            
            return func.HttpResponse(
                json.dumps({"customer": customer}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If no specific identifier, get customers with pagination
        else:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Get optional filter parameters
            loyalty_tier = req.params.get('loyalty_tier')
            cuisine_preference = req.params.get('cuisine_preference')
            dietary_preference = req.params.get('dietary_preference')
            
            # Build filter query
            query = {"is_active": True}
            if loyalty_tier:
                query["loyalty_tier"] = loyalty_tier
            if cuisine_preference:
                query["cuisine_preferences"] = cuisine_preference
            if dietary_preference:
                query["dietary_preferences"] = dietary_preference
            
            # Execute query with pagination
            customers = list(collection.find(query).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            # Remove sensitive information from all customers
            for customer in customers:
                if "password" in customer:
                    del customer["password"]
            
            return func.HttpResponse(
                json.dumps({
                    "customers": customers,
                    "count": len(customers),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving customer: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve customer: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_customer(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Update an existing customer"""
    try:
        # Get customer ID from request
        customer_id = req.params.get('id')
        
        if not customer_id:
            return func.HttpResponse(
                json.dumps({"error": "Customer ID is required for update"}),
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
        
        # Don't allow direct updates to sensitive fields
        protected_fields = ["password", "entra_id", "created_at", "created_by"]
        for field in protected_fields:
            if field in req_body:
                del req_body[field]
        
        try:
            # Check if customer exists
            existing_customer = collection.find_one({"_id": ObjectId(customer_id)})
            if not existing_customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Update the customer
            result = collection.update_one(
                {"_id": ObjectId(customer_id)},
                {"$set": req_body}
            )
            
            if result.modified_count > 0:
                # Get updated customer
                updated_customer = collection.find_one({"_id": ObjectId(customer_id)})
                
                # Remove sensitive information
                if "password" in updated_customer:
                    del updated_customer["password"]
                
                return func.HttpResponse(
                    json.dumps({"message": "Customer updated successfully", "customer": updated_customer}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to customer"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid customer ID format"}),
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
        logging.error(f"Error updating customer: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update customer: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_customer(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Delete (deactivate) a customer"""
    try:
        # Get customer ID from request
        customer_id = req.params.get('id')
        
        if not customer_id:
            return func.HttpResponse(
                json.dumps({"error": "Customer ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if customer exists
            existing_customer = collection.find_one({"_id": ObjectId(customer_id)})
            if not existing_customer:
                return func.HttpResponse(
                    json.dumps({"error": "Customer not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Soft delete (mark as inactive) with user info
            result = collection.update_one(
                {"_id": ObjectId(customer_id)},
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
                    json.dumps({"message": "Customer deleted successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "Customer was already marked as deleted"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid customer ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting customer: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete customer: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )