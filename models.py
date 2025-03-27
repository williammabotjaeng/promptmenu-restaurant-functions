"""
Restaurant Menu Data Models
These models define the structure for restaurant, menu, menu items, and staff data.
"""

from typing import List, Dict, Optional, Union
from datetime import datetime

# Base model for our core objects
class BaseModel:
    def __init__(self, **kwargs):
        self.id = kwargs.get('_id')
        self.created_at = kwargs.get('created_at', datetime.utcnow().isoformat())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow().isoformat())
        self.is_active = kwargs.get('is_active', True)
    
    def to_dict(self) -> Dict:
        """Convert model to dictionary for database storage"""
        return self.__dict__

# MenuItem represents a single dish or product on a menu
class MenuItem(BaseModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = kwargs.get('name', '')
        self.description = kwargs.get('description', '')
        self.price = kwargs.get('price', 0.0)
        self.category = kwargs.get('category', '')
        self.image_url = kwargs.get('image_url', '')
        self.prep_video_url = kwargs.get('prep_video_url', '')  # URL to preparation video
        self.ingredients = kwargs.get('ingredients', [])
        self.allergens = kwargs.get('allergens', [])
        self.nutritional_info = kwargs.get('nutritional_info', {})
        self.tags = kwargs.get('tags', [])  # For filtering (vegan, spicy, etc.)
        self.available = kwargs.get('available', True)
        self.featured = kwargs.get('featured', False)
        self.special_instructions = kwargs.get('special_instructions', '')
        self.preparation_time = kwargs.get('preparation_time', 0)  # in minutes
        self.popularity_score = kwargs.get('popularity_score', 0)  # for sorting

# Menu represents a collection of menu items
class Menu(BaseModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.restaurant_id = kwargs.get('restaurant_id', '')  # Reference to restaurant
        self.name = kwargs.get('name', '')
        self.description = kwargs.get('description', '')
        self.type = kwargs.get('type', 'regular')  # regular, special, seasonal, brunch, etc.
        self.categories = kwargs.get('categories', [])  # List of category names
        self.hours = kwargs.get('hours', {})  # When this menu is available
        self.image_url = kwargs.get('image_url', '')
        self.items = kwargs.get('items', [])  # Can be list of item IDs or embedded items
        self.is_default = kwargs.get('is_default', False)  # Is this the default menu?
        self.language = kwargs.get('language', 'en')  # Support multiple languages
        self.sort_order = kwargs.get('sort_order', {})  # How to sort categories and items

# Staff represents restaurant employees that can be featured on the menu/website
class Staff(BaseModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.restaurant_id = kwargs.get('restaurant_id', '')
        self.name = kwargs.get('name', '')
        self.position = kwargs.get('position', '')  # Chef, Manager, Bartender, etc.
        self.bio = kwargs.get('bio', '')
        self.profile_image = kwargs.get('profile_image', '')
        self.intro_video_url = kwargs.get('intro_video_url', '')
        self.videos = kwargs.get('videos', [])  # List of video URLs
        self.photos = kwargs.get('photos', [])  # List of photo URLs
        self.menu_items = kwargs.get('menu_items', [])  # List of menu item IDs this staff is associated with
        self.specialties = kwargs.get('specialties', [])
        self.social_media = kwargs.get('social_media', {})
        self.awards = kwargs.get('awards', [])
        self.featured = kwargs.get('featured', False)

# Restaurant represents the main business entity
class Restaurant(BaseModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = kwargs.get('name', '')
        self.description = kwargs.get('description', '')
        self.location = kwargs.get('location', {
            'address': '',
            'city': '',
            'state': '',
            'country': '',
            'postal_code': '',
            'coordinates': {
                'latitude': 0.0,
                'longitude': 0.0
            }
        })
        self.contact = kwargs.get('contact', {
            'phone': '',
            'email': '',
            'website': ''
        })
        self.hours = kwargs.get('hours', {
            'monday': {'open': '', 'close': ''},
            'tuesday': {'open': '', 'close': ''},
            'wednesday': {'open': '', 'close': ''},
            'thursday': {'open': '', 'close': ''},
            'friday': {'open': '', 'close': ''},
            'saturday': {'open': '', 'close': ''},
            'sunday': {'open': '', 'close': ''}
        })
        self.owner_id = kwargs.get('owner_id', '')  # Reference to user who owns this restaurant
        self.logo_url = kwargs.get('logo_url', '')
        self.cover_image_url = kwargs.get('cover_image_url', '')
        self.photos = kwargs.get('photos', [])
        self.cuisine_types = kwargs.get('cuisine_types', [])
        self.price_range = kwargs.get('price_range', '')  # $, $$, $$$, $$$$
        self.features = kwargs.get('features', [])  # Outdoor seating, Delivery, etc.
        self.social_media = kwargs.get('social_media', {})
        self.menus = kwargs.get('menus', [])  # References to menu IDs
        self.staff = kwargs.get('staff', [])  # References to staff IDs
        self.avg_rating = kwargs.get('avg_rating', 0.0)
        self.review_count = kwargs.get('review_count', 0)
        self.qr_codes = kwargs.get('qr_codes', [])  # QR codes generated for this restaurant

# Define dictionary to model conversion helper function
def dict_to_model(data: Dict, model_class):
    """Convert database dictionary to model object"""
    if not data:
        return None
    return model_class(**data)

class Customer:
    def __init__(self, **kwargs):
        self.id = kwargs.get('_id')
        self.created_at = kwargs.get('created_at', datetime.utcnow().isoformat())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow().isoformat())
        self.is_active = kwargs.get('is_active', True)
        
        # Basic Information
        self.fullname = kwargs.get('fullname', '')
        self.email = kwargs.get('email', '')
        self.phone_number = kwargs.get('phone_number', '')
        self.profile_image = kwargs.get('profile_image', '')
        
        # Authentication related fields
        self.entra_id = kwargs.get('entra_id')
        self.user_principal_name = kwargs.get('user_principal_name')
        self.password = kwargs.get('password')  # Hashed password
        
        # Address
        self.address = kwargs.get('address', {
            'street': '',
            'city': '',
            'state': '',
            'country': '',
            'postal_code': ''
        })
        
        # Preferences
        self.dietary_preferences = kwargs.get('dietary_preferences', [])  # Vegan, Vegetarian, Gluten-free, etc.
        self.allergens = kwargs.get('allergens', [])  # Nuts, Shellfish, Dairy, etc.
        self.favorite_restaurants = kwargs.get('favorite_restaurants', [])  # List of restaurant IDs
        self.favorite_dishes = kwargs.get('favorite_dishes', [])  # List of menu item IDs
        self.cuisine_preferences = kwargs.get('cuisine_preferences', [])  # Italian, Mexican, Chinese, etc.
        
        # Order History
        self.order_history = kwargs.get('order_history', [])  # List of order IDs
        self.reservations = kwargs.get('reservations', [])  # List of reservation IDs
        
        # Loyalty & Marketing
        self.loyalty_points = kwargs.get('loyalty_points', 0)
        self.loyalty_tier = kwargs.get('loyalty_tier', 'Standard')  # Standard, Silver, Gold, etc.
        self.marketing_preferences = kwargs.get('marketing_preferences', {
            'email': False,
            'sms': False,
            'push': False
        })
        self.referral_code = kwargs.get('referral_code', '')
        self.referrer_id = kwargs.get('referrer_id', '')  # Customer ID who referred this customer
        
        # Analytics & Personalization
        self.last_login = kwargs.get('last_login', '')
        self.visit_count = kwargs.get('visit_count', 0)
        self.average_order_value = kwargs.get('average_order_value', 0.0)
        self.lifetime_value = kwargs.get('lifetime_value', 0.0)
        self.ratings = kwargs.get('ratings', [])  # List of restaurant/item ratings
        
        # Payment Information (references to securely stored payment methods)
        self.payment_methods = kwargs.get('payment_methods', [])  # List of payment method IDs
        
        # Notes and Custom Fields
        self.notes = kwargs.get('notes', '')
        self.custom_fields = kwargs.get('custom_fields', {})
        self.tags = kwargs.get('tags', [])

    def to_dict(self) -> Dict:
        """Convert model to dictionary for database storage"""
        return self.__dict__

def dict_to_customer(data: Dict) -> Optional[Customer]:
    """Convert dictionary to Customer object"""
    if not data:
        return None
    return Customer(**data)

class Order:
    def __init__(self, **kwargs):
        self.id = kwargs.get('_id')
        self.created_at = kwargs.get('created_at', datetime.utcnow().isoformat())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow().isoformat())
        self.is_active = kwargs.get('is_active', True)
        
        # Basic Order Information
        self.order_number = kwargs.get('order_number', '')  # Unique order number (could be auto-generated)
        self.restaurant_id = kwargs.get('restaurant_id', '')  # Reference to restaurant
        self.customer_id = kwargs.get('customer_id', '')  # Reference to customer (can be null for guest orders)
        self.table_number = kwargs.get('table_number', '')  # Physical table or 'Takeout'/'Delivery'
        
        # Order Type and Status
        self.order_type = kwargs.get('order_type', 'dine-in')  # dine-in, takeout, delivery, catering
        self.status = kwargs.get('status', 'pending')  # pending, confirmed, preparing, ready, delivered, completed, cancelled
        
        # Order Items
        self.items = kwargs.get('items', [])  # List of ordered items with customizations
        # Each item structure:
        # {
        #    "item_id": "menu_item_id",
        #    "name": "Item Name",
        #    "quantity": 2,
        #    "unit_price": 12.99,
        #    "subtotal": 25.98,
        #    "special_instructions": "No onions",
        #    "customizations": [
        #      {"name": "Extra cheese", "price": 1.50}
        #    ],
        #    "status": "preparing" (optional item-level status)
        # }
        
        # Financial Information
        self.subtotal = kwargs.get('subtotal', 0.0)  # Sum of all items before tax/tip
        self.tax = kwargs.get('tax', 0.0)
        self.tax_rate = kwargs.get('tax_rate', 0.0)  # As a decimal (e.g., 0.08 for 8%)
        self.tip = kwargs.get('tip', 0.0)
        self.tip_percentage = kwargs.get('tip_percentage', 0.0)  # As a decimal
        self.discount = kwargs.get('discount', 0.0)
        self.discount_code = kwargs.get('discount_code', '')
        self.service_fee = kwargs.get('service_fee', 0.0)
        self.delivery_fee = kwargs.get('delivery_fee', 0.0)
        self.total = kwargs.get('total', 0.0)  # Final amount
        
        # Payment Information
        self.payment_status = kwargs.get('payment_status', 'unpaid')  # unpaid, paid, refunded, partially_refunded
        self.payment_method = kwargs.get('payment_method', '')  # credit_card, cash, mobile_payment, etc.
        self.payment_id = kwargs.get('payment_id', '')  # Reference to payment transaction
        self.payment_time = kwargs.get('payment_time', '')  # When payment was processed
        
        # Delivery Information (if applicable)
        self.delivery_address = kwargs.get('delivery_address', {
            'street': '',
            'city': '',
            'state': '',
            'country': '',
            'postal_code': '',
            'instructions': ''
        })
        self.delivery_time = kwargs.get('delivery_time', '')  # Requested or estimated delivery time
        self.delivery_person_id = kwargs.get('delivery_person_id', '')  # Reference to delivery person
        
        # Timestamps for Order Lifecycle
        self.confirmed_at = kwargs.get('confirmed_at', '')
        self.preparing_at = kwargs.get('preparing_at', '')
        self.ready_at = kwargs.get('ready_at', '')
        self.delivered_at = kwargs.get('delivered_at', '')
        self.completed_at = kwargs.get('completed_at', '')
        self.cancelled_at = kwargs.get('cancelled_at', '')
        self.estimated_ready_time = kwargs.get('estimated_ready_time', '')
        self.actual_ready_time = kwargs.get('actual_ready_time', '')
        
        # Customer Feedback
        self.rating = kwargs.get('rating', 0)  # 1-5 star rating
        self.review = kwargs.get('review', '')
        self.reviewed_at = kwargs.get('reviewed_at', '')
        
        # Staff Information
        self.server_id = kwargs.get('server_id', '')  # Server/waiter who handled the order
        self.chef_id = kwargs.get('chef_id', '')  # Chef who prepared the order
        
        # Additional Information
        self.special_instructions = kwargs.get('special_instructions', '')  # Overall order instructions
        self.allergies = kwargs.get('allergies', [])  # List of allergies to be aware of
        self.occasion = kwargs.get('occasion', '')  # Birthday, anniversary, etc.
        self.loyalty_points_earned = kwargs.get('loyalty_points_earned', 0)
        self.source = kwargs.get('source', 'in-person')  # in-person, website, app, phone, third-party
        
        # For third-party orders (if applicable)
        self.third_party_id = kwargs.get('third_party_id', '')  # Order ID in third-party system
        self.third_party_name = kwargs.get('third_party_name', '')  # e.g., UberEats, DoorDash
        self.third_party_fee = kwargs.get('third_party_fee', 0.0)
        
        # Administrative
        self.notes = kwargs.get('notes', '')  # Internal notes
        self.refund_status = kwargs.get('refund_status', '')  # none, partial, full
        self.refund_amount = kwargs.get('refund_amount', 0.0)
        self.refund_reason = kwargs.get('refund_reason', '')
        self.tags = kwargs.get('tags', [])  # For categorization/filtering

    def to_dict(self) -> Dict:
        """Convert model to dictionary for database storage"""
        return self.__dict__

    def calculate_total(self):
        """Calculate the total amount for the order"""
        self.subtotal = sum(item.get('subtotal', 0) for item in self.items)
        self.tax = round(self.subtotal * self.tax_rate, 2)
        
        # Calculate tip if provided as percentage
        if self.tip_percentage > 0 and self.tip == 0:
            self.tip = round(self.subtotal * self.tip_percentage, 2)
            
        self.total = self.subtotal + self.tax + self.tip + self.service_fee + self.delivery_fee - self.discount
        return self.total

    def add_item(self, item_data):
        """Add an item to the order"""
        # Calculate subtotal for the item
        quantity = item_data.get('quantity', 1)
        unit_price = item_data.get('unit_price', 0)
        customization_total = sum(c.get('price', 0) for c in item_data.get('customizations', []))
        subtotal = (unit_price + customization_total) * quantity
        
        # Add subtotal to item data
        item_data['subtotal'] = subtotal
        
        # Add item to order
        self.items.append(item_data)
        
        # Recalculate total
        self.calculate_total()
        return self

    def update_status(self, new_status):
        """Update the order status and related timestamps"""
        self.status = new_status
        current_time = datetime.utcnow().isoformat()
        
        # Update appropriate timestamp based on status
        if new_status == 'confirmed':
            self.confirmed_at = current_time
        elif new_status == 'preparing':
            self.preparing_at = current_time
        elif new_status == 'ready':
            self.ready_at = current_time
            self.actual_ready_time = current_time
        elif new_status == 'delivered':
            self.delivered_at = current_time
        elif new_status == 'completed':
            self.completed_at = current_time
        elif new_status == 'cancelled':
            self.cancelled_at = current_time
            
        self.updated_at = current_time
        return self

def dict_to_order(data: Dict) -> Optional[Order]:
    """Convert dictionary to Order object"""
    if not data:
        return None
    return Order(**data)

class Review:
    def __init__(self, **kwargs):
        self.id = kwargs.get('_id')
        self.created_at = kwargs.get('created_at', datetime.utcnow().isoformat())
        self.updated_at = kwargs.get('updated_at', datetime.utcnow().isoformat())
        self.is_active = kwargs.get('is_active', True)
        
        # Basic Review Information
        self.review_number = kwargs.get('review_number', '')  # Unique review identifier
        self.restaurant_id = kwargs.get('restaurant_id', '')  # Required relationship to restaurant
        self.customer_id = kwargs.get('customer_id', '')  # Required relationship to customer
        
        # Optional relationships
        self.staff_id = kwargs.get('staff_id', '')  # Optional reference to staff member
        self.menu_item_id = kwargs.get('menu_item_id', '')  # Optional reference to menu item
        self.order_id = kwargs.get('order_id', '')  # Optional reference to an order
        
        # Review content
        self.rating = kwargs.get('rating', 0)  # Rating (typically 1-5)
        self.title = kwargs.get('title', '')  # Optional review title
        self.text = kwargs.get('text', '')  # Text content of the review
        self.date = kwargs.get('date', datetime.utcnow().isoformat())  # When the review was written
        
        # Media content
        self.media = kwargs.get('media', {
            'video': {
                'url': kwargs.get('video_url', ''),
                'duration': kwargs.get('video_duration', 0),
                'content_type': kwargs.get('video_content_type', ''),
                'upload_date': kwargs.get('video_upload_date', '')
            },
            'audio': {
                'url': kwargs.get('audio_url', ''),
                'duration': kwargs.get('audio_duration', 0),
                'content_type': kwargs.get('audio_content_type', ''),
                'upload_date': kwargs.get('audio_upload_date', '')
            },
            'images': kwargs.get('images', [])
            # Each image in the list has format:
            # {
            #   'url': 'image_url',
            #   'caption': 'image caption',
            #   'upload_date': 'timestamp'
            # }
        })
        
        # Review metadata
        self.is_verified = kwargs.get('is_verified', False)  # Whether this is a verified review
        self.verified_by = kwargs.get('verified_by', '')  # Who verified the review
        self.verified_at = kwargs.get('verified_at', '')  # When the review was verified
        self.source = kwargs.get('source', 'direct')  # direct, website, mobile_app, third_party
        self.visit_date = kwargs.get('visit_date', '')  # When the customer visited the restaurant
        
        # Review categorization
        self.tags = kwargs.get('tags', [])  # List of tags associated with this review
        self.categories = kwargs.get('categories', [])  # food, service, ambiance, value, etc.
        self.sentiment = kwargs.get('sentiment', '')  # positive, negative, neutral (could be auto-analyzed)
        
        # Specific ratings (sub-ratings)
        self.sub_ratings = kwargs.get('sub_ratings', {
            'food': kwargs.get('food_rating', 0),
            'service': kwargs.get('service_rating', 0),
            'ambiance': kwargs.get('ambiance_rating', 0),
            'value': kwargs.get('value_rating', 0),
            'cleanliness': kwargs.get('cleanliness_rating', 0)
        })
        
        # Engagement metrics
        self.helpful_count = kwargs.get('helpful_count', 0)  # Number of helpful votes
        self.unhelpful_count = kwargs.get('unhelpful_count', 0)  # Number of unhelpful votes
        self.view_count = kwargs.get('view_count', 0)  # Number of times the review was viewed
        self.flag_count = kwargs.get('flag_count', 0)  # Number of times the review was flagged
        self.flagged_reason = kwargs.get('flagged_reason', [])  # List of reasons the review was flagged
        
        # Response from restaurant
        self.response = kwargs.get('response', {
            'text': kwargs.get('response_text', ''),
            'author_id': kwargs.get('response_author_id', ''),  # Staff member who responded
            'author_title': kwargs.get('response_author_title', ''),  # e.g., "Manager", "Owner"
            'date': kwargs.get('response_date', ''),
            'is_edited': kwargs.get('response_is_edited', False)
        })
        
        # Review state management
        self.status = kwargs.get('status', 'published')  # draft, published, hidden, deleted, under_review
        self.featured = kwargs.get('featured', False)  # Whether this is a featured review
        self.featured_at = kwargs.get('featured_at', '')  # When the review was featured
        self.featured_by = kwargs.get('featured_by', '')  # Who featured the review
        
        # For third-party reviews (if applicable)
        self.third_party_id = kwargs.get('third_party_id', '')  # Review ID in third-party system
        self.third_party_name = kwargs.get('third_party_name', '')  # e.g., Yelp, Google, TripAdvisor
        self.third_party_url = kwargs.get('third_party_url', '')  # URL to the review on the third-party site
        
        # Administrative
        self.notes = kwargs.get('notes', '')  # Internal notes
        self.moderation_notes = kwargs.get('moderation_notes', '')  # Notes from content moderation
        self.moderated_by = kwargs.get('moderated_by', '')  # Who moderated the review
        self.moderated_at = kwargs.get('moderated_at', '')  # When the review was moderated

    def to_dict(self) -> Dict:
        """Convert model to dictionary for database storage"""
        return self.__dict__

    def add_tag(self, tag: str) -> None:
        """Add a tag to the review"""
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.utcnow().isoformat()
            
    def update_rating(self, new_rating: int) -> None:
        """Update the main rating"""
        if 1 <= new_rating <= 5:
            self.rating = new_rating
            self.updated_at = datetime.utcnow().isoformat()
            
    def add_helpful_vote(self) -> None:
        """Increment the helpful vote count"""
        self.helpful_count += 1
        self.updated_at = datetime.utcnow().isoformat()
        
    def add_unhelpful_vote(self) -> None:
        """Increment the unhelpful vote count"""
        self.unhelpful_count += 1
        self.updated_at = datetime.utcnow().isoformat()
        
    def add_response(self, response_text: str, author_id: str, author_title: str) -> None:
        """Add or update a response from the restaurant"""
        self.response = {
            'text': response_text,
            'author_id': author_id,
            'author_title': author_title,
            'date': datetime.utcnow().isoformat(),
            'is_edited': bool(self.response.get('text'))  # True if there was a previous response
        }
        self.updated_at = datetime.utcnow().isoformat()
        
    def update_status(self, new_status: str) -> None:
        """Update the review status"""
        valid_statuses = ['draft', 'published', 'hidden', 'deleted', 'under_review']
        if new_status in valid_statuses:
            self.status = new_status
            self.updated_at = datetime.utcnow().isoformat()
            
    def add_media(self, media_type: str, media_data: Dict) -> None:
        """Add media to the review"""
        if media_type == 'image' and 'url' in media_data:
            if 'images' not in self.media:
                self.media['images'] = []
                
            image = {
                'url': media_data['url'],
                'caption': media_data.get('caption', ''),
                'upload_date': datetime.utcnow().isoformat()
            }
            self.media['images'].append(image)
            
        elif media_type == 'video' and 'url' in media_data:
            self.media['video'] = {
                'url': media_data['url'],
                'duration': media_data.get('duration', 0),
                'content_type': media_data.get('content_type', ''),
                'upload_date': datetime.utcnow().isoformat()
            }
            
        elif media_type == 'audio' and 'url' in media_data:
            self.media['audio'] = {
                'url': media_data['url'],
                'duration': media_data.get('duration', 0),
                'content_type': media_data.get('content_type', ''),
                'upload_date': datetime.utcnow().isoformat()
            }
            
        self.updated_at = datetime.utcnow().isoformat()

def dict_to_review(data: Dict) -> Optional[Review]:
    """Convert dictionary to Review object"""
    if not data:
        return None
    return Review(**data)