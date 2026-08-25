from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"] = Field(..., description="Message author role")
    content: str = Field(..., description="Message content")

    @field_validator("content")
    @classmethod
    def validate_content_length(cls, v: str) -> str:
        if len(v) > 8000:
            raise ValueError("Message content exceeds maximum allowed length of 8000 characters")
        return v

class SelectedInstrumentContext(BaseModel):
    symbol: str
    instrumentType: Optional[str] = "CW"
    issuer: Optional[str] = None
    underlyingSymbol: Optional[str] = None
    strikePrice: Optional[float] = None
    exerciseRatio: Optional[float] = None
    maturityDate: Optional[str] = None
    lastTradingDate: Optional[str] = None
    dte: Optional[str] = None
    underlyingPrice: Optional[float] = None
    bidPrice: Optional[float] = None
    askPrice: Optional[float] = None
    lastPrice: Optional[float] = None
    priceChangePercent: Optional[float] = None
    spread: Optional[float] = None
    spreadPercent: Optional[float] = None
    volume: Optional[int] = None
    ivBid: Optional[float] = None
    ivTrade: Optional[float] = None
    ivAsk: Optional[float] = None
    moneyness: Optional[float] = None
    moneynessLabel: Optional[str] = None
    theoreticalPrice: Optional[float] = None
    historicalVolatility: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None

class ResearchContextEnvelope(BaseModel):
    activePage: Optional[Literal["dashboard", "research"]] = "dashboard"
    selectedInstrument: Optional[SelectedInstrumentContext] = None
    watchlist: Optional[List[str]] = Field(default_factory=list, description="Watched symbols list")
    realtimeStatus: Optional[str] = None
    dataMode: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=30, description="Conversation history")
    context: Optional[ResearchContextEnvelope] = None
    stream: bool = Field(default=True, description="Enable SSE token streaming")

class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str = Field(..., description="Model response text")
    model: str = Field(..., description="Model identifier used for inference")

class HealthResponse(BaseModel):
    status: str = "ok"
    ai_enabled: bool
    model: str
    has_api_key: bool
