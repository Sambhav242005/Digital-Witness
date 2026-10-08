from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging
import os
from typing import Annotated

from fastapi import FastAPI, UploadFile, File, Form, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from .config import Settings
from .errors import ApiFailure
from .schemas import Data, Video, Job, Search, Health, VideoJob, VideoList, SearchAccepted, ErrorEnvelope, ZoneRequest, EmptyRequest, SearchRequest, Chat, ChatCreateRequest, ChatMessageRequest, ChatTurnAccepted
from .service import Service
from .store import identifier
from .media import media_response, MediaError
from .ai.gemini_embedding import GeminiEmbeddingAdapter
from .ai.openrouter_embedding import OpenRouterEmbeddingAdapter
from .ai.gemini_verification import GeminiVerificationAdapter
from .chat import ChatService, GeminiChatAdapter, OpenAICompatibleChatAdapter


def create_app(settings=None, embedding=None, verification=None, chat_adapter=None):
    settings = settings or Settings()
    embedding_provider = os.getenv('EMBEDDING_PROVIDER', 'gemini').lower()
    if embedding is None:
        if embedding_provider == 'openrouter':
            embedding = OpenRouterEmbeddingAdapter()
        elif embedding_provider == 'gemini':
            embedding = GeminiEmbeddingAdapter(model=os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"))
        else:
            raise ValueError('EMBEDDING_PROVIDER must be gemini or openrouter')
    verification = verification or GeminiVerificationAdapter()
    service = Service(settings, embedding, verification)
    if chat_adapter is None:
        chat_provider = os.getenv('CHAT_PROVIDER', 'gemini').lower()
        if chat_provider == 'gemini':
            chat_adapter = GeminiChatAdapter()
        elif chat_provider in ('openai_compatible', 'ollama'):
            chat_adapter = OpenAICompatibleChatAdapter()
        else:
            raise ValueError('CHAT_PROVIDER must be gemini, ollama, or openai_compatible')
    service.chat = ChatService(service, chat_adapter)

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        async def load_models():
            if os.getenv("LOAD_MODELS", "false").lower() == "true":
                for adapter in (embedding, chat_adapter, verification):
                    if service.stop.is_set():
                        return
                    try:
                        await asyncio.to_thread(adapter.load)
                    except Exception:
                        logging.getLogger(__name__).warning("Model adapter unavailable: %s", type(adapter).__name__)
                while not service.stop.is_set():
                    await asyncio.sleep(1)
                    for adapter in (embedding, chat_adapter, verification):
                        if getattr(adapter, "reload_due", False):
                            try:
                                await asyncio.to_thread(adapter.load)
                            except Exception:
                                logging.getLogger(__name__).warning("Model adapter reload unavailable: %s", type(adapter).__name__)
        task = asyncio.create_task(load_models())
        try:
            yield
        finally:
            service.stop.set()
            await task  # Finish in-flight SDK load before closing its client.
            await asyncio.to_thread(service.close)
            for adapter in (embedding, chat_adapter, verification):
                if hasattr(adapter, 'close'):
                    adapter.close()

    errors = {code: {"model": ErrorEnvelope} for code in (404, 409, 413, 415, 422, 429, 500, 503)}
    app = FastAPI(title="Digital Witness", version="1.1", lifespan=lifespan, responses=errors)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["Content-Type", "Range"], expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "Retry-After", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = identifier("req")
        # Bound the whole multipart request before Starlette can spool an oversized
        # upload. Also counts chunked bodies, where Content-Length is absent.
        if request.method == "POST" and request.url.path == "/api/v1/videos":
            maximum = settings.max_upload_bytes + 1024 * 1024
            length = request.headers.get("content-length")
            try:
                if length and int(length) > maximum:
                    return error_response(request, ApiFailure(413, "FILE_TOO_LARGE", "The maximum upload size is 500 MiB."))
            except ValueError:
                return error_response(request, ApiFailure(422, "VALIDATION_ERROR", "Invalid Content-Length."))
            receive = request._receive
            received = 0
            async def bounded_receive():
                nonlocal received
                message = await receive()
                received += len(message.get("body", b""))
                if received > maximum:
                    request.state.upload_too_large = True
                    raise ApiFailure(413, "FILE_TOO_LARGE", "The maximum upload size is 500 MiB.")
                return message
            request._receive = bounded_receive
        try:
            response = await call_next(request)
        except ApiFailure as exc:
            response = error_response(request, exc)
        except Exception:
            logging.getLogger(__name__).error("request=%s unexpected error", request.state.request_id)
            response = error_response(request, ApiFailure(500, "INTERNAL_ERROR", "An internal error occurred. Use the request ID when reporting it."))
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(request, exc):
        return JSONResponse({"error": exc.error, "request_id": getattr(request.state, "request_id", identifier("req"))}, status_code=exc.status, headers={"Retry-After": str(exc.error["details"].get("retry_after_sec", 2))} if exc.status == 429 or exc.error["details"].get("retry_after_sec") else None)

    @app.exception_handler(ApiFailure)
    async def api_error(request, exc):
        return error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        details = {"fields": [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]}
        code = "INVALID_ZONE" if request.url.path.endswith("/zones") else "VALIDATION_ERROR"
        return error_response(request, ApiFailure(422, code, "The request contains invalid fields.", details))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if getattr(request.state, "upload_too_large", False):
            return error_response(request, ApiFailure(413, "FILE_TOO_LARGE", "The maximum upload size is 500 MiB."))
        return error_response(request, ApiFailure(exc.status_code, "VALIDATION_ERROR" if exc.status_code == 400 else "HTTP_ERROR", "The HTTP request could not be handled."))

    @app.get("/api/v1/health", response_model=Data[Health])
    def health():
        return {"data": dict(status="ok", contract_version="1.1", mode="live", capabilities=dict(semantic_search=embedding.available and settings.relevance_threshold is not None, chat=chat_adapter.available, frame_verification=verification.available, temporal_events=False), supported_event_types=[])}

    @app.post("/api/v1/videos", status_code=202, response_model=Data[VideoJob])
    async def upload(request: Request, file: Annotated[UploadFile, File()], camera_label: Annotated[str, Form()]):
        form = await request.form()
        if len(form.getlist("file")) != 1 or len(form.getlist("camera_label")) != 1 or set(form.keys()) != {"file", "camera_label"}:
            raise ApiFailure(422, "VALIDATION_ERROR", "Supply exactly one file and one camera_label.")
        camera_label = camera_label.strip()
        if not 1 <= len(camera_label) <= 80:
            raise ApiFailure(422, "VALIDATION_ERROR", "camera_label must contain 1–80 trimmed characters.")
        if file.content_type not in ("video/mp4", "application/octet-stream") or not (file.filename or "").lower().endswith(".mp4"):
            raise ApiFailure(415, "UNSUPPORTED_MEDIA_TYPE", "Upload an MP4 recording.")
        directory = settings.data_dir / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / (identifier("source") + ".mp4")
        try:
            count = 0
            with source.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    count += len(chunk)
                    if count > settings.max_upload_bytes:
                        raise ApiFailure(413, "FILE_TOO_LARGE", "The maximum upload size is 500 MiB.")
                    output.write(chunk)
            return {"data": service.upload(source, Path(file.filename.replace("\\", "/")).name, camera_label)}
        except BaseException:
            source.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.get("/api/v1/videos", response_model=Data[VideoList])
    def list_videos(limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0)] = 0):
        with service.store.transaction() as db:
            videos = sorted(service.store.all(db, "video"), key=lambda v: (v["created_at"], v["video_id"]), reverse=True)
        return {"data": dict(items=[service.public(v) for v in videos[offset:offset+limit]], total=len(videos), limit=limit, offset=offset)}

    @app.get("/api/v1/videos/{video_id}", response_model=Data[Video])
    def video(video_id: str):
        return {"data": service.get("video", video_id)}

    @app.put("/api/v1/videos/{video_id}/zones", response_model=Data[Video])
    def zones(video_id: str, body: ZoneRequest):
        return {"data": service.zones(video_id, [zone.model_dump() for zone in body.zones])}

    @app.post("/api/v1/videos/{video_id}/index", status_code=202, response_model=Data[VideoJob])
    def index(video_id: str, body: EmptyRequest):
        return {"data": service.kickoff(video_id)}

    @app.post("/api/v1/videos/{video_id}/retry", status_code=202, response_model=Data[VideoJob])
    def retry(video_id: str, body: EmptyRequest):
        return {"data": service.kickoff(video_id, retry=True)}

    @app.get("/api/v1/jobs/{job_id}", response_model=Data[Job])
    def job(job_id: str):
        return {"data": service.get("job", job_id)}

    @app.post("/api/v1/searches", status_code=202, response_model=Data[SearchAccepted])
    def search(body: SearchRequest):
        return {"data": service.search(body.model_dump())}

    @app.get("/api/v1/searches/{search_id}", response_model=Data[Search])
    def search_detail(search_id: str):
        return {"data": service.get("search", search_id)}

    @app.post('/api/v1/chats', status_code=201, response_model=Data[Chat])
    def create_chat(body: ChatCreateRequest):
        return {'data':service.chat.create(body.video_ids)}

    @app.get('/api/v1/chats/{chat_id}', response_model=Data[Chat])
    def chat_detail(chat_id: str):
        return {'data':service.get('chat',chat_id)}

    @app.post('/api/v1/chats/{chat_id}/messages', status_code=202, response_model=Data[ChatTurnAccepted])
    def chat_message(chat_id: str, body: ChatMessageRequest):
        return {'data':service.chat.message(chat_id,body.message)}

    @app.get("/api/v1/media/{media_id}", response_class=Response, response_model=None, responses={200: {"content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}, "image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}, 206: {"description": "Partial media bytes", "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}, "image/jpeg": {"schema": {"type": "string", "format": "binary"}}}}, 416: {"description": "Unsatisfiable byte range"}})
    def get_media(media_id: str, request: Request):
        with service.store.transaction() as db:
            row = db.execute("SELECT path,content_type FROM media WHERE id=?", (media_id,)).fetchone()
        if row is None:
            raise ApiFailure(404, "MEDIA_NOT_FOUND", "The requested media does not exist.")
        path = Path(row["path"]).resolve()
        if not path.is_relative_to(settings.data_dir.resolve()):
            raise ApiFailure(404, "MEDIA_NOT_FOUND", "The requested media does not exist.")
        try:
            return media_response(path, row["content_type"], request.headers.get("range"))
        except MediaError:
            raise ApiFailure(404, "MEDIA_NOT_FOUND", "The requested media is unavailable.") from None

    return app


app = create_app()
