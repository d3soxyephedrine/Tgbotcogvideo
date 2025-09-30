from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

# Initialize SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    """User model to store Telegram users who interact with the bot"""
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(255), nullable=True)
    first_name = db.Column(db.String(255), nullable=True)
    last_name = db.Column(db.String(255), nullable=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_interaction = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    credits = db.Column(db.Integer, default=0, nullable=False)
    
    # One-to-many relationships
    messages = db.relationship('Message', backref='user', lazy=True)
    payments = db.relationship('Payment', backref='user', lazy=True)
    transactions = db.relationship('Transaction', backref='user', lazy=True)

    def __repr__(self):
        return f'<User {self.telegram_id}>'

class Message(db.Model):
    """Message model to store user messages and bot responses"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    model_used = db.Column(db.String(100), nullable=True)
    credits_charged = db.Column(db.Integer, default=1, nullable=False)
    
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