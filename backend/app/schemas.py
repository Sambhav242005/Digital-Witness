"""Canonical v1.1 wire types; request validation stays at the API boundary."""
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VideoStatus = Literal['preparing', 'draft', 'indexing', 'ready', 'failed']
JobStatus = Literal['queued', 'running', 'succeeded', 'failed']
JobKind = Literal['prepare_video', 'index_video', 'search']
EventType = Literal['person_entered', 'possible_unattended_bag']
VerificationStatus = Literal['supported', 'uncertain', 'contradicted', 'not_checked']

class WireModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class ApiError(WireModel):
    code: str
    message: str
    details: dict[str, Any]

class ErrorEnvelope(WireModel):
    error: ApiError
    request_id: str

T = TypeVar('T')
class Data(WireModel, Generic[T]):
    data: T

class Point(WireModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

def _cross(a: Point, b: Point, c: Point) -> float:
    return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)

def _on(a: Point, b: Point, p: Point) -> bool:
    return min(a.x,b.x) <= p.x <= max(a.x,b.x) and min(a.y,b.y) <= p.y <= max(a.y,b.y)

def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    values = (_cross(a,b,c), _cross(a,b,d), _cross(c,d,a), _cross(c,d,b))
    if values[0]*values[1] < 0 and values[2]*values[3] < 0:
        return True
    return any(v == 0 and _on(u,w,p) for v,u,w,p in
               ((values[0],a,b,c),(values[1],a,b,d),(values[2],c,d,a),(values[3],c,d,b)))

class ZoneInput(WireModel):
    name: str = Field(min_length=1)
    kind: Literal['entrance']
    polygon: list[Point] = Field(min_length=3, max_length=12)

    @field_validator('name')
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Zone name must not be blank')
        return value

    @field_validator('polygon')
    @classmethod
    def simple_polygon(cls, points: list[Point]) -> list[Point]:
        n = len(points)
        if len({(p.x,p.y) for p in points}) != n:
            raise ValueError('Polygon vertices must be distinct; do not repeat the first vertex')
        area = sum(points[i].x*points[(i+1)%n].y-points[(i+1)%n].x*points[i].y for i in range(n))
        if area == 0:
            raise ValueError('Polygon must have nonzero area')
        for i in range(n):
            a,b,c = points[i-1],points[i],points[(i+1)%n]
            if _cross(a,b,c) == 0 and (_on(a,b,c) or _on(b,c,a)):
                raise ValueError('Adjacent polygon edges must not overlap')
            for j in range(i+1,n):
                if j == i+1 or (i == 0 and j == n-1):
                    continue
                if _intersects(points[i], points[(i+1)%n], points[j], points[(j+1)%n]):
                    raise ValueError('Polygon must be simple: edges must not cross or touch')
        return points

class Zone(ZoneInput):
    zone_id: str

class ZoneRequest(WireModel):
    zones: list[ZoneInput] = Field(max_length=1)

class EmptyRequest(WireModel):
    pass

class Video(WireModel):
    video_id: str
    filename: str
    camera_label: str
    status: VideoStatus
    created_at: str
    duration_sec: float | None = Field(ge=0)
    width: int | None = Field(gt=0)
    height: int | None = Field(gt=0)
    playback_url: str | None
    thumbnail_url: str | None
    zones: list[Zone]
    active_job_id: str | None
    error: ApiError | None

class Job(WireModel):
    job_id: str
    kind: JobKind
    resource_id: str
    status: JobStatus
    stage: Literal['queued','preparing','embedding','detecting','retrieving','verifying','finalizing','complete','failed']
    progress_pct: float = Field(ge=0, le=100)
    created_at: str
    updated_at: str
    error: ApiError | None

class FrameCheck(WireModel):
    check_id: str
    question: str
    answer: Literal['yes','no','uncertain']
    probability_yes: float | None = Field(ge=0, le=1)

class EvidenceFrame(WireModel):
    timestamp_sec: float = Field(ge=0)
    image_url: str
    quality: Literal['usable','poor']
    checks: list[FrameCheck]

class Verification(WireModel):
    status: VerificationStatus
    reason: str
    basis: Literal['frame_checks','temporal_rule','none']

class TimeRange(WireModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.start_sec >= self.end_sec:
            raise ValueError('start_sec must be less than end_sec')
        return self

class SearchResult(TimeRange):
    result_id: str
    video_id: str
    camera_label: str
    thumbnail_url: str
    playback_url: str
    summary: str
    event_type: EventType | None
    zone_id: str | None
    retrieval_score: float = Field(ge=-1, le=1)
    verification: Verification
    evidence: list[EvidenceFrame]

class SearchRequest(WireModel):
    query: str
    video_ids: list[str] = Field(min_length=1, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)
    time_range: TimeRange | None = None
    event_types: list[EventType] = Field(default_factory=list)

    @field_validator('query')
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 500:
            raise ValueError('Query must contain 1–500 trimmed characters')
        return value

    @field_validator('video_ids')
    @classmethod
    def distinct_ids(cls, ids: list[str]) -> list[str]:
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError('video_ids must contain distinct nonempty IDs')
        return ids

    @model_validator(mode='after')
    def single_time_axis(self):
        if self.time_range is not None and len(self.video_ids) != 1:
            raise ValueError('A time range requires exactly one video_id')
        return self

class SearchWarning(WireModel):
    code: str
    message: str

class Search(WireModel):
    search_id: str
    job_id: str
    status: JobStatus
    query: str
    video_ids: list[str]
    created_at: str
    warnings: list[SearchWarning]
    results: list[SearchResult]
    error: ApiError | None

class Capabilities(WireModel):
    semantic_search: bool
    chat: bool
    frame_verification: bool
    temporal_events: bool

class Health(WireModel):
    status: Literal['ok']
    contract_version: Literal['1.1']
    mode: Literal['live','mock']
    capabilities: Capabilities
    supported_event_types: list[EventType]

class VideoJob(WireModel):
    video: Video
    job: Job

class VideoList(WireModel):
    items: list[Video]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)

class SearchAccepted(WireModel):
    search_id: str
    job: Job


ChatContext = SearchRequest

class ChatCreateRequest(WireModel):
    video_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator('video_ids')
    @classmethod
    def distinct_ids(cls, ids: list[str]) -> list[str]:
        return SearchRequest.distinct_ids(ids)

class ChatMessageRequest(WireModel):
    message: str

    @field_validator('message')
    @classmethod
    def trim_message(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 2000:
            raise ValueError('Message must contain 1–2000 trimmed characters')
        return value

class ChatMessage(WireModel):
    message_id: str
    role: Literal['user', 'assistant']
    text: str
    created_at: str
    search_ids: list[str]
    result_ids: list[str]

class Chat(WireModel):
    chat_id: str
    video_ids: list[str]
    created_at: str
    updated_at: str
    status: Literal['idle', 'running', 'failed']
    active_turn_id: str | None
    context: SearchRequest | None
    messages: list[ChatMessage]
    error: ApiError | None

class ChatTurnAccepted(WireModel):
    chat_id: str
    turn_id: str
