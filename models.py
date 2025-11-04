from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# Initialize SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    """User model to store Telegram users who interact with the bot"""
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(255), nullable=True)
    first_name = db.Column(db.String(255), nullable=True)
    last_name = db.Column(db.String(255), nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_interaction = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    credits = db.Column(db.Integer, default=100, nullable=False)
    
    # Monetization system columns
    daily_credits = db.Column(db.Integer, default=0, nullable=False)
    daily_credits_expiry = db.Column(db.DateTime, nullable=True)
    last_purchase_at = db.Column(db.DateTime, nullable=True)
    last_action_type = db.Column(db.String(100), nullable=True)
    last_action_cost = db.Column(db.Integer, nullable=True)
    last_action_at = db.Column(db.DateTime, nullable=True)
    last_daily_claim_at = db.Column(db.DateTime, nullable=True)
    last_nudge_at = db.Column(db.DateTime, nullable=True)
    
    # API key for web access (LibreChat integration)
    api_key = db.Column(db.String(64), unique=True, nullable=True, index=True)
    
    # Free user limits (paywall counters)
    images_generated = db.Column(db.Integer, default=0, nullable=False)
    images_edited = db.Column(db.Integer, default=0, nullable=False)
    
    # Rate limiting (prevent concurrent message processing)
    processing_since = db.Column(db.DateTime, nullable=True)
    
    # Model selection (deepseek vs gpt4o)
    preferred_model = db.Column(db.String(50), default='deepseek/deepseek-chat-v3.1', nullable=False)
    
    # One-to-many relationships
    messages = db.relationship('Message', backref='user', lazy=True)
    payments = db.relationship('Payment', backref='user', lazy=True)
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    crypto_payments = db.relationship('CryptoPayment', backref='user', lazy=True)
    conversations = db.relationship('Conversation', backref='user', lazy=True, cascade='all, delete-orphan')
    memories = db.relationship('Memory', backref='user', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.telegram_id}>'

class Conversation(db.Model):
    """Conversation model to organize messages into separate chat threads (web only)"""
    __tablename__ = 'conversation'
    __table_args__ = (
        db.Index('idx_user_updated', 'user_id', 'updated_at'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False, default='New Chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # One-to-many relationship with messages
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Conversation {self.id}: {self.title}>'

class Message(db.Model):
    """Message model to store user messages and bot responses"""
    __tablename__ = 'message'
    __table_args__ = (
        db.Index('idx_conversation_created', 'conversation_id', 'created_at'),
        db.Index('idx_conversation_platform', 'conversation_id', 'platform'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id', ondelete='CASCADE'), nullable=True, index=True)
    user_message = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    model_used = db.Column(db.String(100), nullable=True)
    credits_charged = db.Column(db.Integer, default=1, nullable=False)
    platform = db.Column(db.String(20), default='telegram', nullable=False, index=True)
    
    def __repr__(self):
        return f'<Message {self.id} from user {self.user_id}>'

class Payment(db.Model):
    """Payment model to track credit purchases"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    credits_purchased = db.Column(db.Integer, nullable=False)
    stripe_session_id = db.Column(db.String(255), unique=True, nullable=False)
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<Payment {self.id} for user {self.user_id}>'

class Transaction(db.Model):
    """Transaction model to track credit usage"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    credits_used = db.Column(db.Integer, nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    transaction_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Transaction {self.id} for user {self.user_id}>'

class CryptoPayment(db.Model):
    """CryptoPayment model to track cryptocurrency payments via NOWPayments"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    payment_id = db.Column(db.String(255), unique=True, nullable=False)  # NOWPayments payment ID
    order_id = db.Column(db.String(255), unique=True, nullable=False)  # Our internal order ID
    credits_purchased = db.Column(db.Integer, nullable=False)
    price_amount = db.Column(db.Float, nullable=False)  # Amount in fiat currency
    price_currency = db.Column(db.String(10), nullable=False)  # USD, EUR, etc.
    pay_amount = db.Column(db.Float, nullable=True)  # Amount in crypto
    pay_currency = db.Column(db.String(20), nullable=True)  # BTC, ETH, etc.
    pay_address = db.Column(db.String(255), nullable=True)  # Crypto address to send payment
    payment_status = db.Column(db.String(50), nullable=False)  # waiting, confirming, confirmed, finished, failed, etc.
    credits_added = db.Column(db.Boolean, default=False, nullable=False)  # Idempotency flag: tracks if credits were already added
    processed_at = db.Column(db.DateTime, nullable=True)  # Timestamp when credits were added
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<CryptoPayment {self.payment_id} for user {self.user_id}>'

class Memory(db.Model):
    """Memory model to store user-defined persistent memories"""
    __tablename__ = 'memory'
    __table_args__ = (
        db.Index('idx_user_created', 'user_id', 'created_at'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    platform = db.Column(db.String(20), default='telegram', nullable=False)
    
    def __repr__(self):
        return f'<Memory {self.id} for user {self.user_id}>'