"""
Services module - Business logic layer

This module contains service classes that implement
business logic for the application.

Pattern: Service Layer
- Contains business rules
- Orchestrates repository calls
- Handles complex operations
"""

from app.services.auth import AuthService

__all__ = ["AuthService"]
