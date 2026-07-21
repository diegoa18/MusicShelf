class MusicShelfError(Exception):
    """base exception for MusicShelf."""

class ConversionError(MusicShelfError):
    """audio conversion fails"""
