"""
For PostgreSQL
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




"""
══════════════════════════════════════════════════════════════════════════════
OPTION 2 — MongoDB (via PyMongo)                             
 
ENV VARS:
  MONGO_URL=mongodb+srv://user:pass@cluster.mongodb.net/pdf_system
══════════════════════════════════════════════════════════════════════════════
from app.repositories.mongo_repo import MongoUploadRepository, MongoSearchRepository
 
def get_upload_repo() -> AbstractUploadRepository:
    return MongoUploadRepository()
 
def get_search_repo() -> AbstractSearchRepository:
    return MongoSearchRepository()
"""
 
 
"""
══════════════════════════════════════════════════════════════════════════════
OPTION 3 — Oracle Database (via SQLAlchemy + cx_Oracle)     

ENV VARS:
  DATABASE_URL=oracle+cx_oracle://user:pass@host:1521/?service_name=ORCL
 

══════════════════════════════════════════════════════════════════════════════
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.repositories.sql_repo import SQLUploadRepository, SQLSearchRepository
 
def get_upload_repo(db: Session = Depends(get_db)) -> AbstractUploadRepository:
    return SQLUploadRepository(db)
 
def get_search_repo(db: Session = Depends(get_db)) -> AbstractSearchRepository:
    return SQLSearchRepository(db)
"""
 
 
"""
══════════════════════════════════════════════════════════════════════════════
OPTION 4 — Pinecone (Vector Database)                       
 
ENV VARS:
  PINECONE_API_KEY=your-api-key
  PINECONE_INDEX_NAME=pdf-chunks
  OPENAI_API_KEY=your-key
  MONGO_URL=mongodb+srv://...   (still needed for upload metadata)
══════════════════════════════════════════════════════════════════════════════
from app.repositories.mongo_repo import MongoUploadRepository
from app.repositories.pinecone_repo import PineconeSearchRepository
 
def get_upload_repo() -> AbstractUploadRepository:
    return MongoUploadRepository()
 
def get_search_repo() -> AbstractSearchRepository:
    return PineconeSearchRepository()
"""
 
 
"""
══════════════════════════════════════════════════════════════════════════════
OPTION 5 — Redis Search (RediSearch module)                 

ENV VARS:
  REDIS_URL=redis://...   (already set — no new variable needed)
  DATABASE_URL=...        (still needed for upload metadata)
 

══════════════════════════════════════════════════════════════════════════════
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.repositories.sql_repo import SQLUploadRepository
from app.repositories.redis_search_repo import RedisSearchRepository
 
def get_upload_repo(db: Session = Depends(get_db)) -> AbstractUploadRepository:
    return SQLUploadRepository(db)
 
def get_search_repo() -> AbstractSearchRepository:
    return RedisSearchRepository()
"""
 