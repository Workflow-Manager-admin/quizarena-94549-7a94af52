from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    Depends, status, HTTPException
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from passlib.context import CryptContext
import secrets

DATABASE_URL = "sqlite:///./quizrealm.db"


# DB setup

engine = sa.create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Password hashing ctx
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# Models
class User(Base):
    __tablename__ = "users"

    id = sa.Column(sa.Integer, primary_key=True, index=True)
    username = sa.Column(sa.String(32), unique=True, index=True, nullable=False)
    email = sa.Column(sa.String(64), unique=True, index=True, nullable=False)
    hashed_password = sa.Column(sa.String(128), nullable=False)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow)
    matches = relationship('Match', back_populates='user')


class QuizRoom(Base):
    __tablename__ = "quiz_rooms"

    id = sa.Column(sa.Integer, primary_key=True, index=True)
    code = sa.Column(sa.String(8), unique=True, index=True, nullable=False)
    name = sa.Column(sa.String(32), nullable=False)
    is_active = sa.Column(sa.Boolean, default=True)
    current_question = sa.Column(sa.Integer, default=0)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow)
    matches = relationship('Match', back_populates='room')


class Question(Base):
    __tablename__ = "questions"

    id = sa.Column(sa.Integer, primary_key=True, index=True)
    quiz_room_id = sa.Column(sa.Integer, sa.ForeignKey('quiz_rooms.id'))
    text = sa.Column(sa.String, nullable=False)
    options = sa.Column(sa.String, nullable=False)  # comma separated options
    answer = sa.Column(sa.Integer, nullable=False)  # index of correct option
    order = sa.Column(sa.Integer, default=0)


class Match(Base):
    __tablename__ = "matches"

    id = sa.Column(sa.Integer, primary_key=True, index=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id"))
    room_id = sa.Column(sa.Integer, sa.ForeignKey("quiz_rooms.id"))
    score = sa.Column(sa.Integer, default=0)
    started_at = sa.Column(sa.DateTime, default=datetime.utcnow)
    ended_at = sa.Column(sa.DateTime)
    user = relationship('User', back_populates='matches')
    room = relationship('QuizRoom', back_populates='matches')
    responses = relationship('Response', back_populates='match')


class Response(Base):
    __tablename__ = "responses"

    id = sa.Column(sa.Integer, primary_key=True, index=True)
    match_id = sa.Column(sa.Integer, sa.ForeignKey("matches.id"))
    question_id = sa.Column(sa.Integer, sa.ForeignKey("questions.id"))
    selected_option = sa.Column(sa.Integer, nullable=False)
    is_correct = sa.Column(sa.Boolean, default=False)
    answered_at = sa.Column(sa.DateTime, default=datetime.utcnow)
    match = relationship('Match', back_populates='responses')


# Create tables
Base.metadata.create_all(bind=engine)


# Pydantic schemas
class RegisterUser(BaseModel):
    username: str = Field(..., max_length=32, description="Unique username.")
    email: str = Field(..., max_length=64)
    password: str = Field(..., min_length=5)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class UserPublic(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        orm_mode = True


class RoomInfo(BaseModel):
    code: str
    name: str
    current_question: int
    is_active: bool


class QuestionOut(BaseModel):
    id: int
    text: str
    options: List[str]
    order: int

    class Config:
        orm_mode = True


class LeaderboardEntry(BaseModel):
    username: str
    score: int


class DashboardStats(BaseModel):
    total_matches: int
    avg_score: float
    best_score: int
    last_match: Optional[str]


class MatchHistoryEntry(BaseModel):
    room_code: str
    score: int
    started_at: str
    ended_at: str


# FastAPI app init
app = FastAPI(
    title="QuizRealm Backend API",
    description="Backend API for the QuizRealm multiplayer quiz app.",
    version="1.0.0",
    openapi_tags=[
        {"name": "auth", "description": "Registration and authentication"},
        {"name": "quiz", "description": "Quiz game and live rooms APIs"},
        {"name": "analytics", "description": "User dashboard and analytics"},
        {"name": "misc", "description": "Miscellaneous endpoints"},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility fns for auth and db
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(sub: str, expires_delta: timedelta = timedelta(hours=2)):
    # NOTE: not JWT; very simple token for demonstration; in prod use JWT!
    token = secrets.token_hex(32)
    return token


# User session for demonstration (in-memory). For production, use persistent token storage.
active_tokens: Dict[str, int] = {}  # token: user_id


# PUBLIC_INTERFACE
@app.post("/auth/register", response_model=UserPublic, tags=["auth"], summary="Register a new user")
async def register(payload: RegisterUser, db: Session = Depends(get_db)):
    """Register a new user with username, email, and password."""
    if db.query(User).filter(
        (User.username == payload.username) | (User.email == payload.email)
    ).first():
        raise HTTPException(status_code=400, detail="Username or email already taken")
    hashed = hash_password(payload.password)
    user = User(username=payload.username, email=payload.email, hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# PUBLIC_INTERFACE
@app.post("/auth/login", response_model=TokenResponse, tags=["auth"], summary="Login user to get access token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Log in with username and password, and receive an access token."""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(sub=str(user.id))
    active_tokens[token] = user.id
    return {"access_token": token, "token_type": "bearer"}


# PUBLIC_INTERFACE
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Get currently authenticated user from token."""
    user_id = active_tokens.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# PUBLIC_INTERFACE
@app.get("/rooms", response_model=List[RoomInfo], tags=["quiz"], summary="List all active quiz rooms")
async def list_rooms(db: Session = Depends(get_db)):
    """Get all currently active quiz rooms."""
    rooms = db.query(QuizRoom).filter(QuizRoom.is_active.is_(True)).all()
    return [
        RoomInfo(
            code=room.code,
            name=room.name,
            current_question=room.current_question,
            is_active=room.is_active
        )
        for room in rooms
    ]


# PUBLIC_INTERFACE
@app.post("/rooms/join", tags=["quiz"], summary="Join a quiz room and start a match")
async def join_room(
    room_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Join an active quiz room and start a new match session. Returns match ID and room info."""
    room = db.query(QuizRoom).filter(
        QuizRoom.code == room_code,
        QuizRoom.is_active.is_(True)
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or inactive")
    # Create or resume a match for this user
    match = db.query(Match).filter_by(
        user_id=user.id, room_id=room.id, ended_at=None
    ).first()
    if not match:
        match = Match(user_id=user.id, room_id=room.id, score=0)
        db.add(match)
        db.commit()
        db.refresh(match)
    return {
        "match_id": match.id,
        "room_code": room.code,
        "room_name": room.name
    }


# ---------------------------
# Real-time quiz logic (WebSocket)
# ---------------------------

class QuizWSMessage(BaseModel):
    action: str  # join, answer, leaderboard
    question_id: Optional[int]
    selected_option: Optional[int]


# In-memory state for WebSocket quiz rooms.
class RoomConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.match_for_ws: Dict[WebSocket, Dict[str, Any]] = {}

    async def connect(
        self, room_code: str, websocket: WebSocket,
        match_id: int, user_id: int
    ):
        await websocket.accept()
        if room_code not in self.active_connections:
            self.active_connections[room_code] = []
        self.active_connections[room_code].append(websocket)
        self.match_for_ws[websocket] = {"match_id": match_id, "user_id": user_id}

    def disconnect(self, room_code: str, websocket: WebSocket):
        if room_code in self.active_connections:
            self.active_connections[room_code].remove(websocket)
        if websocket in self.match_for_ws:
            del self.match_for_ws[websocket]

    async def broadcast(self, room_code: str, message: dict):
        for ws in self.active_connections.get(room_code, []):
            await ws.send_json(message)


room_ws_manager = RoomConnectionManager()


# PUBLIC_INTERFACE
@app.websocket("/ws/quiz/{room_code}")
async def quiz_room_ws(websocket: WebSocket, room_code: str, token: str):
    """
    WebSocket for real-time quiz room play.

    Notes:
    - Client must connect with valid `token` as URL param. 
    - On connect: Send {"action": "joined", "question": {...}}.
    - On answer: Send {"action": "answer", "question_id": id, "selected_option": idx}.
    - Receive leaderboard after each question.

    OperationId: quizRoomRealtimeWebsocket
    """
    db = SessionLocal()
    user_id = active_tokens.get(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    room = db.query(QuizRoom).filter(
        QuizRoom.code == room_code,
        QuizRoom.is_active.is_(True)
    ).first()
    if not room:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    # Resume or create match if not present
    match = db.query(Match).filter_by(
        user_id=user.id, room_id=room.id, ended_at=None
    ).first()
    if not match:
        match = Match(user_id=user.id, room_id=room.id, score=0)
        db.add(match)
        db.commit()
        db.refresh(match)
    await room_ws_manager.connect(room_code, websocket, match.id, user.id)
    try:
        q = db.query(Question).filter(
            Question.quiz_room_id == room.id,
            Question.order == room.current_question
        ).first()
        if q:
            await websocket.send_json({
                "action": "joined",
                "question": {
                    "id": q.id,
                    "text": q.text,
                    "options": q.options.split(","),
                    "order": q.order
                }
            })
        while True:
            data = await websocket.receive_json()
            msg = QuizWSMessage(**data)
            if msg.action == "answer":
                question = db.query(Question).filter(
                    Question.id == msg.question_id
                ).first()
                if not question:
                    await websocket.send_json({"error": "Invalid question ID"})
                    continue
                is_correct = (msg.selected_option == question.answer)
                resp = Response(
                    match_id=match.id,
                    question_id=question.id,
                    selected_option=msg.selected_option,
                    is_correct=is_correct
                )
                db.add(resp)
                db.commit()
                if is_correct:
                    match.score += 10
                    db.commit()
                all_matches = db.query(Match).filter_by(
                    room_id=room.id, ended_at=None
                ).all()
                leaderboard = [
                    {"username": m.user.username, "score": m.score}
                    for m in sorted(all_matches, key=lambda mm: -mm.score)
                ]
                await room_ws_manager.broadcast(room_code, {
                    "action": "leaderboard",
                    "leaderboard": leaderboard
                })
                next_q = db.query(Question).filter(
                    Question.quiz_room_id == room.id,
                    Question.order == question.order + 1
                ).first()
                if next_q:
                    room.current_question += 1
                    db.commit()
                    await room_ws_manager.broadcast(room_code, {
                        "action": "next_question",
                        "question": {
                            "id": next_q.id,
                            "text": next_q.text,
                            "options": next_q.options.split(","),
                            "order": next_q.order
                        }
                    })
                else:
                    room.is_active = False
                    db.commit()
                    match.ended_at = datetime.utcnow()
                    db.commit()
                    await room_ws_manager.broadcast(room_code, {
                        "action": "quiz_end",
                        "leaderboard": leaderboard
                    })
                    break
    except WebSocketDisconnect:
        room_ws_manager.disconnect(room_code, websocket)
    finally:
        db.close()


# PUBLIC_INTERFACE
@app.get(
    "/user/dashboard",
    response_model=DashboardStats,
    tags=["analytics"],
    summary="User dashboard analytics"
)
async def user_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns user performance analytics, e.g., matches played, best/avg score, last match date."""
    matches = db.query(Match).filter_by(user_id=user.id).all()
    if not matches:
        return DashboardStats(
            total_matches=0, avg_score=0, best_score=0, last_match=None
        )
    scores = [m.score for m in matches]
    last_match = max((m.ended_at for m in matches if m.ended_at), default=None)
    return DashboardStats(
        total_matches=len(matches),
        avg_score=sum(scores) / len(scores),
        best_score=max(scores),
        last_match=last_match.isoformat() if last_match else None
    )


# PUBLIC_INTERFACE
@app.get(
    "/user/history",
    response_model=List[MatchHistoryEntry],
    tags=["analytics"],
    summary="Get match history for user"
)
async def match_history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return all matches that the user has participated in, ordered by most recent."""
    entries = []
    matches = db.query(Match).filter_by(
        user_id=user.id
    ).order_by(Match.started_at.desc()).all()
    for m in matches:
        entries.append(
            MatchHistoryEntry(
                room_code=m.room.code,
                score=m.score,
                started_at=m.started_at.isoformat(),
                ended_at=m.ended_at.isoformat() if m.ended_at else ""
            )
        )
    return entries


# PUBLIC_INTERFACE
@app.get(
    "/quiz-check",
    tags=["misc"],
    summary="Health check for QuizRealm backend"
)
def quiz_check():
    """Health check endpoint to confirm backend is running."""
    return {"status": "QuizRealm backend running"}


# Root route for initial health check
@app.get(
    "/",
    tags=["misc"],
    summary="Basic health check route (legacy)"
)
def root_route():
    """Basic health check endpoint (legacy)."""
    return {"message": "Healthy"}


# ---------------------------
# Utility: seed demo data if empty
# ---------------------------
@app.on_event("startup")
def seed_demo_data():
    db = SessionLocal()
    if not db.query(QuizRoom).first():
        room = QuizRoom(code="ROOM123", name="General Knowledge")
        db.add(room)
        db.commit()
        questions = [
            Question(
                quiz_room_id=room.id,
                text="Capital of France?",
                options="Paris,Berlin,Madrid,London",
                answer=0,
                order=0,
            ),
            Question(
                quiz_room_id=room.id,
                text="Fastest land animal?",
                options="Cheetah,Lion,Antelope,Tiger",
                answer=0,
                order=1,
            ),
            Question(
                quiz_room_id=room.id,
                text="Who wrote '1984'?",
                options="Orwell,Wells,Huxley,Bradbury",
                answer=0,
                order=2,
            )
        ]
        db.add_all(questions)
        db.commit()
    db.close()


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=(
            app.description +
            "\n\nNote: `/ws/quiz/{room_code}` is a WebSocket endpoint for real-time quiz."
        ),
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
