class MusicShelfError(Exception):
    """base exception for MusicShelf."""

class ConversionError(MusicShelfError):
    """audio conversion fails"""

class ValidationError(MusicShelfError):
    """URL or metadata validation fails"""
