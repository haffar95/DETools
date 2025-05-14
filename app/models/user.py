from werkzeug.security import generate_password_hash, check_password_hash
from typing import List, Optional
import json
import os

class User:
    def __init__(self, username: str, password: str = None, is_admin: bool = False):
        self.username = username
        self.password_hash = generate_password_hash(password) if password else None
        self.is_admin = is_admin
        self.allowed_connections: List[str] = []
        self.users_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'users.json')

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            'username': self.username,
            'password_hash': self.password_hash,
            'is_admin': self.is_admin,
            'allowed_connections': self.allowed_connections
        }

    @staticmethod
    def from_dict(data: dict) -> 'User':
        user = User(data['username'])
        user.password_hash = data['password_hash']
        user.is_admin = data.get('is_admin', False)
        user.allowed_connections = data.get('allowed_connections', [])
        return user

    def save_users(self, users: List['User']) -> None:
        users_data = [user.to_dict() for user in users]
        with open(self.users_file, 'w') as f:
            json.dump(users_data, f, indent=4)

    def load_users(self) -> List['User']:
        if not os.path.exists(self.users_file):
            # Create default admin user if file doesn't exist
            admin = User('admin', 'admin123', True)
            self.save_users([admin])
            return [admin]

        with open(self.users_file, 'r') as f:
            users_data = json.load(f)
            return [User.from_dict(user_data) for user_data in users_data]

    @staticmethod
    def get_user(username: str) -> Optional['User']:
        user = User(username)
        users = user.load_users()
        return next((u for u in users if u.username == username), None)

    def add_connection(self, connection_name: str) -> bool:
        if connection_name not in self.allowed_connections:
            self.allowed_connections.append(connection_name)
            users = self.load_users()
            for i, user in enumerate(users):
                if user.username == self.username:
                    users[i] = self
                    break
            self.save_users(users)
            return True
        return False

    def remove_connection(self, connection_name: str) -> bool:
        if connection_name in self.allowed_connections:
            self.allowed_connections.remove(connection_name)
            users = self.load_users()
            for i, user in enumerate(users):
                if user.username == self.username:
                    users[i] = self
                    break
            self.save_users(users)
            return True
        return False

    def can_access_connection(self, connection_name: str) -> bool:
        from app.validation.validators import DataValidator
        validator = DataValidator()
        configs = validator.get_database_configs()
        config = next((c for c in configs if c['name'] == connection_name), None)
        return self.is_admin or (config and config.get('creator') == self.username)