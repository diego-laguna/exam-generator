from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import DbSession, require_role
from app.models import Role, User
from app.security import password_hash

router = APIRouter(prefix="/users", tags=["users"])

Username = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
# Upper bound keeps argon2 hashing cost bounded for oversized inputs.
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    username: Username
    password: Password
    role: Role = Role.student


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime


class UsernameTaken(Exception):
    pass


def create_user(db: Session, username: str, password: str, role: Role) -> User:
    user = User(username=username, password_hash=password_hash.hash(password), role=role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise UsernameTaken(username)
    db.refresh(user)
    return user


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.admin))],
)
def create_user_endpoint(body: UserCreate, db: DbSession):
    try:
        return create_user(db, body.username, body.password, body.role)
    except UsernameTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
