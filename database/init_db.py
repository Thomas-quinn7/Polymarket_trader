"""
Database Initialization
Initialize SQLite database with all required tables
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from data.polymarket_models import Base
from utils.logger import logger


def init_db():
    """Initialize database with all tables"""
    try:
        engine = create_engine("sqlite:///polymarket.db", echo=False)

        # Create all tables
        Base.metadata.create_all(engine)

        # Create session factory
        Session = sessionmaker(bind=engine)

        logger.info("Database initialized with all tables")
        return engine, Session
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise
