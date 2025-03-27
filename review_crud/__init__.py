"""
Review CRUD Operations
Functions for creating, reading, updating, and deleting review data.
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
    def wrapper(req, *args, **kwargs):
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
        return func(req, *args, **kwargs)
    
    return wrapper

def update_restaurant_rating(restaurant_id, restaurant_collection, review_collection):
    """Update the average rating and review count for a restaurant"""
    try:
        # Get all active reviews for the restaurant
        reviews = list(review_collection.find(
            {"restaurant_id": restaurant_id, "is_active": True, "status": "published"}
        ))
        
        # Calculate average rating
        if reviews:
            ratings = [review.get("rating", 0) for review in reviews]
            avg_rating = sum(ratings) / len(ratings)
        else:
            avg_rating = 0
        
        # Update restaurant with new average rating and review count
        restaurant_collection.update_one(
            {"_id": ObjectId(restaurant_id)},
            {
                "$set": {
                    "avg_rating": round(avg_rating, 1),
                    "review_count": len(reviews),
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        return True
    except Exception as e:
        logging.error(f"Error updating restaurant rating: {str(e)}")
        return False

def get_restaurant_owner(restaurant_id, restaurant_collection):
    """Get the owner ID of a restaurant"""
    try:
        restaurant = restaurant_collection.find_one({"_id": ObjectId(restaurant_id)})
        if restaurant:
            return restaurant.get("owner_id", "")
        return ""
    except Exception as e:
        logging.error(f"Error getting restaurant owner: {str(e)}")
        return ""

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing review CRUD operation.')
    
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
        review_container = os.environ.get("REVIEW_CONTAINER", "Reviews")
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
        review_collection = database[review_container]
        restaurant_collection = database[restaurant_container]  # For updating restaurant ratings
        
        # Get operation type from route or query parameter
        route = req.route_params.get('operation', '')
        operation = route if route else req.params.get('operation', 'get')
        
        # Handle different CRUD operations
        if req.method == 'POST' and operation.lower() == 'create':
            return create_review(req, review_collection, restaurant_collection)
        elif req.method == 'GET' and operation.lower() == 'get':
            return get_review(req, review_collection)
        elif req.method == 'PUT' and operation.lower() == 'update':
            return update_review(req, review_collection, restaurant_collection)
        elif req.method == 'DELETE' and operation.lower() == 'delete':
            return delete_review(req, review_collection, restaurant_collection)
        elif req.method == 'PUT' and operation.lower() == 'respond':
            return respond_to_review(req, review_collection)
        elif req.method == 'POST' and operation.lower() == 'helpful':
            return mark_review_helpful(req, review_collection)
        else:
            return func.HttpResponse(
                json.dumps({"error": f"Unsupported operation: {operation}"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error processing review operation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"An unexpected error occurred: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def create_review(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Create a new review"""
    try:
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        required_fields = ["restaurant_id", "rating", "text"]
        if not all(field in req_body for field in required_fields):
            missing_fields = [field for field in required_fields if field not in req_body]
            return func.HttpResponse(
                json.dumps({"error": f"Missing required fields: {', '.join(missing_fields)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Validate rating range
        if not (1 <= req_body["rating"] <= 5):
            return func.HttpResponse(
                json.dumps({"error": "Rating must be between 1 and 5"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Set customer_id from token if not provided
        if "customer_id" not in req_body:
            req_body["customer_id"] = req.token_data.get("oid", "")
        
        # Add timestamps
        current_time = datetime.utcnow().isoformat()
        req_body["created_at"] = current_time
        req_body["updated_at"] = current_time
        req_body["date"] = current_time  # Special field for the review date
        
        # Generate review number if not provided
        if "review_number" not in req_body:
            # Simple review number generation
            prefix = "REV"
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            req_body["review_number"] = f"{prefix}-{timestamp}"
        
        # Set default values
        if "is_active" not in req_body:
            req_body["is_active"] = True
        if "status" not in req_body:
            req_body["status"] = "published"
        if "helpful_count" not in req_body:
            req_body["helpful_count"] = 0
        if "unhelpful_count" not in req_body:
            req_body["unhelpful_count"] = 0
        if "view_count" not in req_body:
            req_body["view_count"] = 0
        
        # Initialize media object if not provided
        if "media" not in req_body:
            req_body["media"] = {
                "images": [],
                "video": {
                    "url": "",
                    "duration": 0,
                    "content_type": "",
                    "upload_date": ""
                },
                "audio": {
                    "url": "",
                    "duration": 0,
                    "content_type": "",
                    "upload_date": ""
                }
            }
        
        # Initialize response object if not provided
        if "response" not in req_body:
            req_body["response"] = {
                "text": "",
                "author_id": "",
                "author_title": "",
                "date": "",
                "is_edited": False
            }
        
        # Initialize sub_ratings if not provided
        if "sub_ratings" not in req_body:
            req_body["sub_ratings"] = {
                "food": 0,
                "service": 0,
                "ambiance": 0,
                "value": 0,
                "cleanliness": 0
            }
        
        # Verify the restaurant exists
        restaurant_id = req_body["restaurant_id"]
        restaurant = restaurant_collection.find_one({"_id": ObjectId(restaurant_id)})
        if not restaurant:
            return func.HttpResponse(
                json.dumps({"error": "Restaurant not found"}),
                status_code=404,
                mimetype="application/json"
            )
        
        # Create the review
        result = collection.insert_one(req_body)
        
        # Get created review with _id
        created_review = collection.find_one({"_id": result.inserted_id})
        
        # Update restaurant rating
        update_restaurant_rating(restaurant_id, restaurant_collection, collection)
        
        return func.HttpResponse(
            json.dumps({"message": "Review created successfully", "review": created_review}, cls=JSONEncoder),
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
        logging.error(f"Error creating review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to create review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def get_review(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Get review(s) by ID, review number, customer ID, or restaurant ID"""
    try:
        # Check for identification parameters
        review_id = req.params.get('id')
        review_number = req.params.get('review_number')
        customer_id = req.params.get('customer_id')
        restaurant_id = req.params.get('restaurant_id')
        
        # If an ID was provided, get review by ID
        if review_id:
            try:
                review = collection.find_one({"_id": ObjectId(review_id), "is_active": True})
            except:
                return func.HttpResponse(
                    json.dumps({"error": "Invalid review ID format"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            if not review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Increment view count
            collection.update_one(
                {"_id": ObjectId(review_id)},
                {"$inc": {"view_count": 1}}
            )
            
            return func.HttpResponse(
                json.dumps({"review": review}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If review number was provided, get review by review number
        elif review_number:
            review = collection.find_one({"review_number": review_number, "is_active": True})
            
            if not review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Increment view count
            collection.update_one(
                {"review_number": review_number},
                {"$inc": {"view_count": 1}}
            )
            
            return func.HttpResponse(
                json.dumps({"review": review}, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If customer ID was provided, get all reviews for that customer
        elif customer_id:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Query for reviews by customer
            reviews = list(collection.find(
                {"customer_id": customer_id, "is_active": True, "status": "published"}
            ).sort("date", -1).skip(skip).limit(limit))
            
            total_count = collection.count_documents(
                {"customer_id": customer_id, "is_active": True, "status": "published"}
            )
            
            return func.HttpResponse(
                json.dumps({
                    "reviews": reviews,
                    "count": len(reviews),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If restaurant ID was provided, get all reviews for that restaurant
        elif restaurant_id:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Get optional filter parameters
            min_rating = req.params.get('min_rating')
            max_rating = req.params.get('max_rating')
            sort_by = req.params.get('sort_by', 'date')  # date, helpful
            
            # Build filter query
            query = {"restaurant_id": restaurant_id, "is_active": True, "status": "published"}
            
            if min_rating:
                query["rating"] = {"$gte": int(min_rating)}
                
            if max_rating:
                if "rating" in query:
                    query["rating"]["$lte"] = int(max_rating)
                else:
                    query["rating"] = {"$lte": int(max_rating)}
            
            # Determine sort order
            sort_field = "date"
            if sort_by == "helpful":
                sort_field = "helpful_count"
            
            # Execute query with pagination
            reviews = list(collection.find(query).sort(sort_field, -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            # Calculate rating distribution
            rating_distribution = {}
            for rating in range(1, 6):
                rating_distribution[str(rating)] = collection.count_documents({
                    "restaurant_id": restaurant_id,
                    "is_active": True,
                    "status": "published",
                    "rating": rating
                })
            
            return func.HttpResponse(
                json.dumps({
                    "reviews": reviews,
                    "count": len(reviews),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit,
                    "rating_distribution": rating_distribution
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
        
        # If no specific ID was provided, get all reviews with pagination
        else:
            # Get pagination parameters
            page = int(req.params.get('page', 1))
            limit = int(req.params.get('limit', 10))
            skip = (page - 1) * limit
            
            # Build filter query
            query = {"is_active": True, "status": "published"}
            
            # Execute query with pagination
            reviews = list(collection.find(query).sort("date", -1).skip(skip).limit(limit))
            total_count = collection.count_documents(query)
            
            return func.HttpResponse(
                json.dumps({
                    "reviews": reviews,
                    "count": len(reviews),
                    "total_count": total_count,
                    "page": page,
                    "total_pages": (total_count + limit - 1) // limit
                }, cls=JSONEncoder),
                status_code=200,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error retrieving review(s): {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to retrieve review(s): {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def update_review(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Update an existing review"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required for update"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Add updated timestamp
        req_body["updated_at"] = datetime.utcnow().isoformat()
        
        # Remove _id if present (can't update _id)
        if "_id" in req_body:
            del req_body["_id"]
        
        # Don't allow direct updates to certain fields
        protected_fields = ["created_at", "created_by", "helpful_count", "unhelpful_count", 
                          "view_count", "customer_id", "review_number"]
        for field in protected_fields:
            if field in req_body:
                del req_body[field]
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Verify the user owns this review
            user_id = req.token_data.get("oid", "")
            is_admin = "admin" in req.token_data.get("roles", [])
            is_owner = user_id and user_id == existing_review.get("customer_id")
            
            if not (is_admin or is_owner):
                return func.HttpResponse(
                    json.dumps({"error": "Unauthorized. Only the review author or admins can update this review"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Update the review
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {"$set": req_body}
            )
            
            # If rating is updated, recalculate restaurant rating
            if "rating" in req_body and req_body["rating"] != existing_review.get("rating"):
                restaurant_id = existing_review["restaurant_id"]
                update_restaurant_rating(restaurant_id, restaurant_collection, collection)
            
            if result.modified_count > 0:
                # Get updated review
                updated_review = collection.find_one({"_id": ObjectId(review_id)})
                
                return func.HttpResponse(
                    json.dumps({"message": "Review updated successfully", "review": updated_review}, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid review ID format"}),
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
        logging.error(f"Error updating review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to update review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def delete_review(req: func.HttpRequest, collection, restaurant_collection) -> func.HttpResponse:
    """Delete (hide) a review"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required for deletion"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Verify the user owns this review or is an admin
            user_id = req.token_data.get("oid", "")
            is_admin = "admin" in req.token_data.get("roles", [])
            is_owner = user_id and user_id == existing_review.get("customer_id")
            restaurant_owner = user_id and user_id == get_restaurant_owner(existing_review["restaurant_id"], restaurant_collection)
            
            if not (is_admin or is_owner or restaurant_owner):
                return func.HttpResponse(
                    json.dumps({"error": "Unauthorized. Only the review author, restaurant owner, or admins can delete this review"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Soft delete (mark as inactive) with user info
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {
                    "$set": {
                        "is_active": False,
                        "status": "deleted",
                        "updated_at": datetime.utcnow().isoformat(),
                        "deleted_by": req.token_data.get("preferred_username", "unknown"),
                        "deleted_at": datetime.utcnow().isoformat()
                    }
                }
            )
            
            # Update restaurant rating
            restaurant_id = existing_review["restaurant_id"]
            update_restaurant_rating(restaurant_id, restaurant_collection, collection)
            
            if result.modified_count > 0:
                return func.HttpResponse(
                    json.dumps({"message": "Review deleted successfully"}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "Review was already marked as deleted"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid review ID format"}),
                status_code=400,
                mimetype="application/json"
            )
    
    except Exception as e:
        logging.error(f"Error deleting review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to delete review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def respond_to_review(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Add a response to a review (for restaurant owners/staff)"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required for adding a response"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        if "response_text" not in req_body:
            return func.HttpResponse(
                json.dumps({"error": "Response text is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Add or update response
            response_text = req_body["response_text"]
            author_id = req.token_data.get("oid", "")
            author_title = req_body.get("author_title", "Restaurant Representative")
            current_time = datetime.utcnow().isoformat()
            
            # Check if there's an existing response
            is_edited = bool(existing_review.get("response", {}).get("text"))
            
            # Create the response object
            response = {
                "text": response_text,
                "author_id": author_id,
                "author_title": author_title,
                "date": current_time,
                "is_edited": is_edited
            }
            
            # Update the review with the response
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {
                    "$set": {
                        "response": response,
                        "updated_at": current_time
                    }
                }
            )
            
            if result.modified_count > 0:
                # Get updated review
                updated_review = collection.find_one({"_id": ObjectId(review_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": "Response added successfully",
                        "review": updated_review
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except:
            return func.HttpResponse(
                json.dumps({"error": "Invalid review ID format"}),
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
        logging.error(f"Error adding response to review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to add response to review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def mark_review_helpful(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Mark a review as helpful or unhelpful"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Determine if helpful or unhelpful
        is_helpful = req_body.get("helpful", True)
        field_to_increment = "helpful_count" if is_helpful else "unhelpful_count"
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Update the helpful/unhelpful count
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {"$inc": {field_to_increment: 1}}
            )
            
            if result.modified_count > 0:
                # Get updated review
                updated_review = collection.find_one({"_id": ObjectId(review_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": f"Review marked as {'helpful' if is_helpful else 'unhelpful'}",
                        "review": updated_review
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except Exception as e:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid review ID format or error: {str(e)}"}),
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
        logging.error(f"Error marking review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to mark review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def flag_review(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Flag a review for inappropriate content"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Get flag reason
        flag_reason = req_body.get("flag_reason", "Inappropriate content")
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Update flagged information
            current_time = datetime.utcnow().isoformat()
            
            # Add the new flag reason to the list
            flagged_reasons = existing_review.get("flagged_reason", [])
            if flag_reason not in flagged_reasons:
                flagged_reasons.append(flag_reason)
            
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {
                    "$set": {
                        "flagged_reason": flagged_reasons,
                        "updated_at": current_time
                    },
                    "$inc": {"flag_count": 1}
                }
            )
            
            # If flag count exceeds threshold, change status to under_review
            updated_review = collection.find_one({"_id": ObjectId(review_id)})
            flag_threshold = int(os.environ.get("FLAG_THRESHOLD", 5))
            
            if updated_review.get("flag_count", 0) >= flag_threshold and updated_review.get("status") == "published":
                collection.update_one(
                    {"_id": ObjectId(review_id)},
                    {"$set": {"status": "under_review"}}
                )
                updated_review["status"] = "under_review"
            
            if result.modified_count > 0:
                return func.HttpResponse(
                    json.dumps({
                        "message": "Review flagged successfully",
                        "review": updated_review
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except Exception as e:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid review ID format or error: {str(e)}"}),
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
        logging.error(f"Error flagging review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to flag review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def moderate_review(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Moderate a review (for admins)"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Validate required fields
        if "status" not in req_body:
            return func.HttpResponse(
                json.dumps({"error": "Status is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        new_status = req_body.get("status")
        valid_statuses = ["published", "hidden", "deleted"]
        
        if new_status not in valid_statuses:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}),
                status_code=400,
                mimetype="application/json"
            )
        
        moderation_notes = req_body.get("moderation_notes", "")
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Verify user is an admin
            is_admin = "admin" in req.token_data.get("roles", [])
            
            if not is_admin:
                return func.HttpResponse(
                    json.dumps({"error": "Unauthorized. Only admins can moderate reviews"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Update the review status
            current_time = datetime.utcnow().isoformat()
            moderator = req.token_data.get("preferred_username", "unknown")
            
            update_data = {
                "status": new_status,
                "updated_at": current_time,
                "moderated_by": moderator,
                "moderated_at": current_time,
                "moderation_notes": moderation_notes
            }
            
            # If deleting, also mark inactive
            if new_status == "deleted":
                update_data["is_active"] = False
                update_data["deleted_by"] = moderator
                update_data["deleted_at"] = current_time
            
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {"$set": update_data}
            )
            
            # If status changed, update restaurant rating
            if result.modified_count > 0 and existing_review.get("status") != new_status:
                # This would need the restaurant_collection passed as a parameter
                # For now we'll log this action for awareness
                logging.info(f"Restaurant rating should be updated for restaurant_id: {existing_review.get('restaurant_id')}")
            
            if result.modified_count > 0:
                # Get updated review
                updated_review = collection.find_one({"_id": ObjectId(review_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": f"Review moderated successfully. Status set to {new_status}",
                        "review": updated_review
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except Exception as e:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid review ID format or error: {str(e)}"}),
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
        logging.error(f"Error moderating review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to moderate review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )

@require_auth
def feature_review(req: func.HttpRequest, collection) -> func.HttpResponse:
    """Feature or unfeature a review (for restaurant owners/admins)"""
    try:
        # Get review ID from request
        review_id = req.params.get('id')
        
        if not review_id:
            return func.HttpResponse(
                json.dumps({"error": "Review ID is required"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # Get request body
        req_body = req.get_json()
        
        # Determine if featuring or unfeaturing
        featured = req_body.get("featured", True)
        
        try:
            # Check if review exists
            existing_review = collection.find_one({"_id": ObjectId(review_id)})
            if not existing_review:
                return func.HttpResponse(
                    json.dumps({"error": "Review not found"}),
                    status_code=404,
                    mimetype="application/json"
                )
            
            # Only allow featuring if the review is published
            if featured and existing_review.get("status") != "published":
                return func.HttpResponse(
                    json.dumps({"error": "Only published reviews can be featured"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            # Update featured status
            current_time = datetime.utcnow().isoformat()
            user = req.token_data.get("preferred_username", "unknown")
            
            update_data = {
                "featured": featured,
                "updated_at": current_time
            }
            
            if featured:
                update_data["featured_at"] = current_time
                update_data["featured_by"] = user
            
            result = collection.update_one(
                {"_id": ObjectId(review_id)},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                # Get updated review
                updated_review = collection.find_one({"_id": ObjectId(review_id)})
                
                return func.HttpResponse(
                    json.dumps({
                        "message": f"Review {'featured' if featured else 'unfeatured'} successfully",
                        "review": updated_review
                    }, cls=JSONEncoder),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse(
                    json.dumps({"message": "No changes made to review"}),
                    status_code=200,
                    mimetype="application/json"
                )
        
        except Exception as e:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid review ID format or error: {str(e)}"}),
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
        logging.error(f"Error featuring review: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Failed to feature review: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )