"""
Order CRUD Operations
Functions for creating, reading, updating, and deleting order data.
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
    logging.info('Processing order CRUD operation.')
    
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
        order_container = os.environ.get("ORDER_CONTAINER", "Orders")
        
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
        order_collection = database[order_container]
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_order(req, order_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_order(req, order_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_order(req, order_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_order(req, order_collection)
        elif req.method == 'PUT' and operation.lower() == 'status':
            return update_order_status(req, order_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing order operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_order(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Create a new order"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["restaurant_id", "items"]
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
        
        # Generate order number if not provided
        if "order_number" not in req_body:
            # Simple order number generation - could be more sophisticated in production
            prefix = "ORD"
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            req_body["order_number"] = f"{prefix}-{timestamp}"
        
        # Set default values
        if "is_active" not in req_body:
            req_body["is_active"] = True
        if "status" not in req_body:
            req_body["status"] = "pending"
        if "payment_status" not in req_body:
            req_body["payment_status"] = "unpaid"
        
        # Initialize financial calculations if not provided
        items = req_body.get("items", [])
        subtotal = 0
        
        # Calculate subtotal from items if not explicitly provided
        for item in items:
            quantity = item.get("quantity", 1)
            unit_price = item.get("unit_price", 0)
            customization_total = sum(c.get("price", 0) for c in item.get("customizations", []))
            item_subtotal = (unit_price + customization_total) * quantity
            
            # Update or add subtotal to item
            item["subtotal"] = item_subtotal
            subtotal += item_subtotal
        
        # Set or update subtotal
        req_body["subtotal"] = subtotal
        
        # Calculate tax if tax_rate is provided
        tax_rate = req_body.get("tax_rate", 0)
        if tax_rate > 0:
            req_body["tax"] = round(subtotal * tax_rate, 2)
        elif "tax" not in req_body:
            req_body["tax"] = 0
        
        # Calculate tip if tip_percentage is provided
        tip_percentage = req_body.get("tip_percentage", 0)
        if tip_percentage > 0 and "tip" not in req_body:
            req_body["tip"] = round(subtotal * tip_percentage, 2)
        elif "tip" not in req_body:
            req_body["tip"] = 0
        
        # Set service fee and delivery fee to 0 if not provided
        if "service_fee" not in req_body:
            req_body["service_fee"] = 0
        if "delivery_fee" not in req_body:
            req_body["delivery_fee"] = 0
        if "discount" not in req_body:
            req_body["discount"] = 0
        
        # Calculate total
        req_body["total"] = (
            req_body["subtotal"] + 
            req_body["tax"] + 
            req_body["tip"] + 
            req_body["service_fee"] + 
            req_body["delivery_fee"] - 
            req_body["discount"]
        )
        
        # Create the order
        result = collection.insert_one(req_body)
        
        # Get created order with _id
        created_order = collection.find_one({"_id": result.inserted_id})
        
        return func.HttpResponse(
            json.dumps({"message": "Order created successfully", "order": created_order}, cls=JSONEncoder),
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
        logging.error(f"Error creating order: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create order: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_order(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Get order(s) by ID, order number, customer ID, or restaurant ID"""
    try:
        # Check for identification parameters
        order_id = req.params.get('id')
        order_number = req.params.get('order_number')
        customer_id = req.params.get('customer_id')
        restaurant_id = req.params.get('restaurant_id')
        status = req.params.get('status')
        
        # If an ID was provided, get order by ID
        if order_id:
            try:
                order = collection.find_one({"_id": ObjectId(order_id)})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid order ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not order:
                return func.HttpResponse(
                    json.dumps({"error": "Order not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"order": order}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If order number was provided, get order by order number
        elif order_number:
            order = collection.find_one({"order_number": order_number})
            
            if not order:
                return func.HttpResponse(
                    json.dumps({"error": "Order not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"order": order}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If customer ID was provided, get all orders for that customer
        elif customer_id:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Build query
            query = {"customer_id": customer_id}
            if status:
                query["status"] = status
            
            # Execute query
            orders = list(collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "orders": orders,
                    "count": len(orders),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If restaurant ID was provided, get all orders for that restaurant
        elif restaurant_id:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Build query
            query = {"restaurant_id": restaurant_id}
            if status:
                query["status"] = status
            
            # Execute query
            orders = list(collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "orders": orders,
                    "count": len(orders),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If no specific ID was provided, get all orders with pagination
        else:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Build query
            query = {}
            if status:
                query["status"] = status
            
            # Time range filtering
            start_date = req.params.get('start_date')
            end_date = req.params.get('end_date')
            if start_date or end_date:
                query["created_at"] = {}
                if start_date:
                    query["created_at"]["$gte"] = start_date
                if end_date:
                    query["created_at"]["$lte"] = end_date
            
            # Execute query
            orders = list(collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "orders": orders,
                    "count": len(orders),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving order(s): {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve order(s): {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_order(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Update an existing order"""
    try:
        # Get order ID from request
        order_id = req.params.get('id')
        
        if not order_id:
            return func.HttpResponse(
                json.dumps({"error": "Order ID is required for update"}),
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
            # Check if order exists
            existing_order = collection.find_one({"_id": ObjectId(order_id)})
            if not existing_order:
                return func.HttpResponse(
                    json.dumps({"error": "Order not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # If items are updated, recalculate subtotal and total
            if "items" in req_body:
                items = req_body.get("items", [])
                subtotal = 0
                
                # Calculate subtotal from items
                for item in items:
                    quantity = item.get("quantity", 1)
                    unit_price = item.get("unit_price", 0)
                    customization_total = sum(c.get("price", 0) for c in item.get("customizations", []))
                    item_subtotal = (unit_price + customization_total) * quantity
                    
                    # Update or add subtotal to item
                    item["subtotal"] = item_subtotal
                    subtotal += item_subtotal
                
                # Set or update subtotal
                req_body["subtotal"] = subtotal
                
                # Calculate tax if tax_rate is provided or use existing tax_rate
                tax_rate = req_body.get("tax_rate", existing_order.get("tax_rate", 0))
                if tax_rate > 0:
                    req_body["tax"] = round(subtotal * tax_rate, 2)
                
                # Calculate tip if tip_percentage is provided or use existing tip
                tip_percentage = req_body.get("tip_percentage", existing_order.get("tip_percentage", 0))
                if tip_percentage > 0 and "tip" not in req_body:
                    req_body["tip"] = round(subtotal * tip_percentage, 2)
                
                # Calculate total if financial fields are updated
                service_fee = req_body.get("service_fee", existing_order.get("service_fee", 0))
                delivery_fee = req_body.get("delivery_fee", existing_order.get("delivery_fee", 0))
                discount = req_body.get("discount", existing_order.get("discount", 0))
                tax = req_body.get("tax", existing_order.get("tax", 0))
                tip = req_body.get("tip", existing_order.get("tip", 0))
                
                req_body["total"] = (
                    subtotal + 
                    tax + 
                    tip + 
                    service_fee + 
                    delivery_fee - 
                    discount
                )
            
            # Update the order
            result = collection.update_one(
                {"_id": ObjectId(order_id)},
                {"$set": req_body}
            )
            
            if result.modified_count > 0:
                # Get updated order
                updated_order = collection.find_one({"_id": ObjectId(order_id)})
                
                return func.HttpResponse(
                    json.dumps({"message": "Order updated successfully", "order": updated_order}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to order"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid order ID format"}),
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
        logging.error(f"Error updating order: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update order: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_order_status(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Update the status of an order"""
    try:
        # Get order ID from request
        order_id = req.params.get('id')
        
        if not order_id:
            return func.HttpResponse(
                json.dumps({"error": "Order ID is required for status update"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Validate that status is provided
        if "status" not in req_body:
            return func.HttpResponse(
                json.dumps({"error": "Status is required for status update"}),
                status_code=400,
                mimetype="application/json"
            )
        
        new_status = req_body["status"]
        valid_statuses = ["pending", "confirmed", "preparing", "ready", "delivered", "completed", "cancelled"]
        
        if new_status not in valid_statuses:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if order exists
            existing_order = collection.find_one({"_id": ObjectId(order_id)})
            if not existing_order:
                return func.HttpResponse(
                    json.dumps({"error": "Order not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Prepare update data
            update_data = {
                "status": new_status,
                "updated_at": datetime.utcnow().isoformat(),
                "updated_by": req.token_data.get("preferred_username", "unknown")
            }
            
            # Add status-specific timestamp
            current_time = datetime.utcnow().isoformat()
            if new_status == "confirmed":
                update_data["confirmed_at"] = current_time
            elif new_status == "preparing":
                update_data["preparing_at"] = current_time
            elif new_status == "ready":
                update_data["ready_at"] = current_time
                update_data["actual_ready_time"] = current_time
            elif new_status == "delivered":
                update_data["delivered_at"] = current_time
            elif new_status == "completed":
                update_data["completed_at"] = current_time
            elif new_status == "cancelled":
                update_data["cancelled_at"] = current_time
            
            # Update the order
            result = collection.update_one(
                {"_id": ObjectId(order_id)},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                # Get updated order
                updated_order = collection.find_one({"_id": ObjectId(order_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": f"Order status updated to {new_status} successfully",
                        "order": updated_order
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to order status"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid order ID format"}),
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
        logging.error(f"Error updating order status: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update order status: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_order(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Delete (cancel) an order"""
    try:
        # Get order ID from request
        order_id = req.params.get('id')
        
        if not order_id:
            return func.HttpResponse(
                json.dumps({"error": "Order ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if order exists
            existing_order = collection.find_one({"_id": ObjectId(order_id)})
            if not existing_order:
                return func.HttpResponse(
                    json.dumps({"error": "Order not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Check if order is already cancelled
            if existing_order.get("status") == "cancelled":
                return func.HttpResponse(
                    json.dumps({"message": "Order is already cancelled"}),
                    status_code=200,
                    mimetype="application/json"
                )
            
            # Get cancellation reason from request body
            cancellation_reason = ""
            try:
                req_body = req.get_json()
                cancellation_reason = req_body.get("cancellation_reason", "")
            except:
                # If no request body or invalid JSON, continue without cancellation reason
                pass
            
            # Cancel the order
            result = collection.update_one(
                {"_id": ObjectId(order_id)},
                {
                    "$set": {
                        "status": "cancelled",
                        "is_active": False,
                        "updated_at": datetime.utcnow().isoformat(),
                        "cancelled_at": datetime.utcnow().isoformat(),
                        "cancelled_by": req.token_data.get("preferred_username", "unknown"),
                        "cancellation_reason": cancellation_reason
                    }
                }
            )
            
            if result.modified_count > 0:
                return func.HttpResponse(
                    json.dumps({"message": "Order cancelled successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to order"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid order ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting order: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete order: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )