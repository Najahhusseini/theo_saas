from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from database import get_db
import models
import logging

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    Get the current user from the JWT token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        logger.info("🔑 Decoding JWT token")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        hotel_id: int = payload.get("hotel_id")
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        
        logger.info(f"Token payload - email: {email}, hotel_id: {hotel_id}, user_id: {user_id}, role: {role}")
        
        if email is None:
            logger.error("Email not found in token")
            raise credentials_exception
            
    except JWTError as e:
        logger.error(f"JWT Error: {e}")
        raise credentials_exception

    # Query user from database
    user = db.query(models.User).filter(models.User.email == email).first()

    if user is None:
        logger.error(f"User not found in database: {email}")
        raise credentials_exception
    
    # Check if user is active (if the field exists)
    if hasattr(user, 'active') and user.active is False:
        logger.error(f"User account is deactivated: {email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )
    
    logger.info(f"✅ User authenticated: {user.email} (ID: {user.id}, Role: {user.role})")
    return user

def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    logger.info(f"Hashing password of length: {len(password)}")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password
    """
    try:
        logger.info(f"Verifying password - plain length: {len(plain_password)}, hash length: {len(hashed_password)}")
        
        if not plain_password or not hashed_password:
            logger.error("Empty password or hash provided")
            return False
            
        result = pwd_context.verify(plain_password, hashed_password)
        logger.info(f"Password verification result: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def create_access_token(data: dict) -> str:
    """
    Create a JWT access token
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    
    # Add issued at time
    to_encode.update({"iat": datetime.utcnow()})
    
    logger.info(f"Creating access token for user: {data.get('sub')}")
    logger.info(f"Token data: { {k:v for k,v in to_encode.items() if k != 'exp'} }")
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"Token created successfully, length: {len(encoded_jwt)}")
    
    return encoded_jwt

def create_refresh_token(data: dict) -> str:
    """
    Create a refresh token with longer expiry
    """
    to_encode = data.copy()
    # Refresh token expires in 7 days
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})
    
    logger.info(f"Creating refresh token for user: {data.get('sub')}")
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    """
    Decode a token without validation (for debugging)
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.error(f"Token decode error: {e}")
        return None