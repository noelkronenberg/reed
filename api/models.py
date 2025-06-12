from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import os
from dotenv import load_dotenv

load_dotenv('.env.local')

db = SQLAlchemy()

# initialize encryption key
encryption_key = os.getenv('ENCRYPTION_KEY')
cipher_suite = Fernet(encryption_key)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(512))
    
    # encrypted API keys
    zotero_user_id_encrypted = db.Column(db.String(512))
    zotero_api_key_encrypted = db.Column(db.String(512))
    semantic_scholar_api_key_encrypted = db.Column(db.String(512))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_zotero_user_id(self, user_id):
        self.zotero_user_id_encrypted = cipher_suite.encrypt(user_id.encode()).decode()

    def get_zotero_user_id(self):
        if self.zotero_user_id_encrypted:
            return cipher_suite.decrypt(self.zotero_user_id_encrypted.encode()).decode()
        return None

    def set_zotero_api_key(self, api_key):
        self.zotero_api_key_encrypted = cipher_suite.encrypt(api_key.encode()).decode()

    def get_zotero_api_key(self):
        if self.zotero_api_key_encrypted:
            return cipher_suite.decrypt(self.zotero_api_key_encrypted.encode()).decode()
        return None

    def set_semantic_scholar_api_key(self, api_key):
        self.semantic_scholar_api_key_encrypted = cipher_suite.encrypt(api_key.encode()).decode()

    def get_semantic_scholar_api_key(self):
        if self.semantic_scholar_api_key_encrypted:
            return cipher_suite.decrypt(self.semantic_scholar_api_key_encrypted.encode()).decode()
        return None 