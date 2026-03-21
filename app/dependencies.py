"""
Dependency injection wiring.

THIS IS THE ONE FILE YOU CHANGE TO SWAP THE DATABASE.

Example — switch to a hypothetical Pinecone implementation:
    from app.repositories.pinecone_repo import PineconeSearchRepository
    def get_search_repo(...) -> AbstractSearchRepository:
        return PineconeSearchRepository()

The controllers and services never import concrete repos directly.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.repositories.sql_repo import SQLUploadRepository, SQLSearchRepository


def get_upload_repo(db: Session = Depends(get_db)) -> AbstractUploadRepository:
    return SQLUploadRepository(db)


def get_search_repo(db: Session = Depends(get_db)) -> AbstractSearchRepository:
    return SQLSearchRepository(db)
