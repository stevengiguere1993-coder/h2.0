"""
Repositories module - Data access layer

This module contains repository classes that handle
database operations for each model.

Pattern: Repository Pattern
- Abstracts data access logic
- Provides clean interface for services
- Enables testing with mocks
"""

from app.repositories.user import UserRepository

__all__ = ["UserRepository"]
