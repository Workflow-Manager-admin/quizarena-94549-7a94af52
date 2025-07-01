# ...[everything above remains unchanged]...

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
    entries = []
    matches = (
        db.query(Match)
        .filter_by(user_id=user.id)
        .order_by(Match.started_at.desc())
        .all()
    )
    for m in matches:
        entries.append(
            MatchHistoryEntry(
                room_code=m.room.code,
                score=m.score,
                started_at=m.started_at.isoformat(),
                ended_at=(
                    m.ended_at.isoformat()
                    if m.ended_at
                    else ""
                ),
            )
        )
    return entries

# ...[everything below remains unchanged]...
@app.get(
    "/quiz-check",
    tags=["misc"],
    summary="Health check for QuizRealm backend"
)
def quiz_check():
    return {"status": "QuizRealm backend running"}


@app.get(
    "/",
    tags=["misc"],
    summary="Basic health check route (legacy)"
)
def root_route():
    return {"message": "Healthy"}


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
            app.description
            + "\n\nNote: `/ws/quiz/{room_code}` is a WebSocket endpoint for real-time quiz."
        ),
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
