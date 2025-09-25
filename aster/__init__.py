"""
Aster Finance API Client Package

This package provides a Python client for interacting with the Aster Finance Futures API.

Classes:
    AsterFinanceClient: Main API client for Aster Finance
    ConfigLoader: Configuration loader for API credentials

Usage:
    from aster import AsterFinanceClient, ConfigLoader
    
    # Load configuration
    config = ConfigLoader()
    
    # Create API client
    client = AsterFinanceClient(
        api_key=config.get_api_key(),
        secret_key=config.get_secret_key()
    )
    
    # Use the client
    server_time = client.get_server_time()
"""

from .aster_api_client import AsterFinanceClient
from .config_loader import ConfigLoader

__version__ = "1.0.0"
__author__ = "Aster Finance API Client"

__all__ = [
    "AsterFinanceClient",
    "ConfigLoader"
]