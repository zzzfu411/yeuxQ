"""Independent versioned API for read-only, non-canonical workbench data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import FastAPI, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from yeuxq.contracts import ContractValidationError, SymbolId
from yeuxq.intel.report_store import (
    ReportExpiredError,
    ReportNotFoundError,
    ReportPathError,
    ReportStoreError,
    ReportValidationError,
    ReportId,
)
from yeuxq.api.routes_v1 import ADVISORY_BOUNDARY


log = logging.getLogger("yeuxq.api.advisory_v1")

SAFE_SYMBOL = r"^[0-9]{6}$"
SAFE_REPORT_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
SAFE_SUBJECT = r"^(?:[0-9]{6}|WATCH)$"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AdvisoryServiceProvider(Protocol):
    def search_instruments(self, keyword: str, limit: int) -> Mapping[str, Any]: ...

    def watchlist_quotes(self, symbols: list[str]) -> Mapping[str, Any]: ...

    def market_overview(self) -> Mapping[str, Any]: ...

    def symbol_analysis(self, symbol: str, period: str) -> Mapping[str, Any]: ...

    def symbol_minute(self, symbol: str) -> Mapping[str, Any]: ...

    def list_reports(self, subject: str | None, limit: int) -> Mapping[str, Any]: ...

    def get_report(self, report_id: str) -> Mapping[str, Any]: ...


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else uuid4().hex


def _boundary() -> dict[str, object]:
    return dict(ADVISORY_BOUNDARY)


def _response(
    request: Request,
    *,
    status_code: int,
    data: object | None = None,
    error: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "yeuxq_advisory_request_id", _request_id(request))
    payload: dict[str, object] = {
        "request_id": request_id,
        "advisory": _boundary(),
    }
    if error is None:
        payload["data"] = data
    else:
        payload["error"] = error
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


def _error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return _response(
        request,
        status_code=status_code,
        error={"code": code, "message": message},
    )


def _iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _analysis_projection(payload: Mapping[str, Any], now: datetime) -> dict[str, object]:
    if payload.get("error"):
        return {
            "availability": "UNAVAILABLE",
            "event_time": None,
            "stale_after": None,
            "freshness": "UNKNOWN",
        }
    sources = payload.get("meta", {}).get("data_sources", {})
    if not isinstance(sources, Mapping) or not sources:
        return {
            "availability": "AVAILABLE",
            "event_time": None,
            "stale_after": None,
            "freshness": "UNKNOWN",
        }
    availability = "AVAILABLE"
    states: list[str] = []
    ages: list[float] = []
    remaining: list[float] = []
    for item in sources.values():
        if not isinstance(item, Mapping):
            states.append("UNKNOWN")
            continue
        if item.get("status") in {"degraded", "unavailable"}:
            availability = "DEGRADED"
        fresh = item.get("freshness")
        if not isinstance(fresh, Mapping):
            states.append("UNKNOWN")
            continue
        state = str(fresh.get("state") or "UNKNOWN").upper()
        age = fresh.get("age_seconds")
        ttl = fresh.get("ttl_seconds")
        if state == "STALE":
            states.append("STALE")
        elif state in {"FRESH", "HIT"}:
            states.append("FRESH")
        else:
            states.append("UNKNOWN")
        if isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0:
            ages.append(float(age))
            if isinstance(ttl, (int, float)) and not isinstance(ttl, bool) and ttl > age:
                remaining.append(float(ttl) - float(age))
    freshness = (
        "STALE"
        if "STALE" in states
        else "UNKNOWN"
        if not states or "UNKNOWN" in states
        else "FRESH"
    )
    event_time = now - timedelta(seconds=max(ages)) if ages else None
    stale_after = (
        now + timedelta(seconds=min(remaining)) if remaining and freshness == "FRESH" else None
    )
    return {
        "availability": availability,
        "event_time": event_time.isoformat() if event_time else None,
        "stale_after": stale_after.isoformat() if stale_after else None,
        "freshness": freshness,
    }


def _report_projection(payload: Mapping[str, Any], now: datetime) -> dict[str, object]:
    candidates: Sequence[Mapping[str, Any]]
    items = payload.get("items")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        candidates = [item for item in items if isinstance(item, Mapping)]
    else:
        candidates = [payload]
    created = [_iso(item.get("created_at")) for item in candidates]
    expires = [_iso(item.get("expires_at")) for item in candidates]
    valid_created = [value for value in created if value is not None and value <= now]
    valid_expires = [value for value in expires if value is not None]
    invalid_timing = not candidates or any(
        created_at is None or expires_at is None or created_at > now or expires_at <= created_at
        for created_at, expires_at in zip(created, expires, strict=True)
    )
    stale = any(value <= now for value in valid_expires)
    freshness = "STALE" if stale else "UNKNOWN" if invalid_timing else "FRESH"
    return {
        "availability": "AVAILABLE",
        "event_time": max(valid_created).isoformat() if valid_created else None,
        "stale_after": min(valid_expires).isoformat() if valid_expires else None,
        "freshness": freshness,
    }


def _project(capability: str, payload: Mapping[str, Any]) -> dict[str, object]:
    required = {
        "availability",
        "event_time",
        "received_at",
        "stale_after",
        "freshness",
        "provenance",
    }
    if required <= set(payload):
        if (
            payload.get("availability") not in {"AVAILABLE", "DEGRADED", "UNAVAILABLE"}
            or payload.get("freshness") not in {"FRESH", "STALE", "UNKNOWN"}
            or not isinstance(payload.get("provenance"), Mapping)
        ):
            raise ValueError("provider evidence projection is invalid")
        return {
            **dict(payload),
            "canonical": False,
            "can_upgrade_gate": False,
        }
    now = datetime.now(timezone.utc)
    if capability == "analysis":
        timing = _analysis_projection(payload, now)
    elif capability in {"reports", "report"}:
        timing = _report_projection(payload, now)
    else:
        unavailable = bool(payload.get("error"))
        degraded = bool(payload.get("unavailable_symbols"))
        timing = {
            "availability": "UNAVAILABLE"
            if unavailable
            else "DEGRADED"
            if degraded
            else "AVAILABLE",
            "event_time": None,
            "stale_after": None,
            "freshness": "UNKNOWN",
        }
    return {
        **timing,
        "received_at": now.isoformat(),
        "provenance": {
            "authority": "yeuxq/advisory-workbench",
            "capability": capability,
            "canonical": False,
        },
        "canonical": False,
        "can_upgrade_gate": False,
        "payload": dict(payload),
    }


def create_advisory_app(provider: AdvisoryServiceProvider) -> FastAPI:
    app = FastAPI(
        title="yeuxQ advisory workbench API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    @app.middleware("http")
    async def advisory_contract(request: Request, call_next):
        request.state.yeuxq_advisory_request_id = _request_id(request)
        try:
            response = await call_next(request)
        except (ReportNotFoundError, ReportExpiredError):
            return _error(request, 404, "REPORT_NOT_FOUND", "report was not found")
        except (
            ContractValidationError,
            ReportValidationError,
            ReportPathError,
            ValueError,
            TypeError,
        ):
            return _error(request, 422, "INVALID_REQUEST", "request was rejected")
        except ReportStoreError:
            return _error(request, 503, "SERVICE_UNAVAILABLE", "report service is unavailable")
        except Exception:
            log.exception(
                "unhandled advisory service failure",
                extra={"request_id": request.state.yeuxq_advisory_request_id},
            )
            return _error(request, 503, "SERVICE_UNAVAILABLE", "advisory service is unavailable")
        response.headers["X-Request-ID"] = request.state.yeuxq_advisory_request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        return _error(request, 422, "INVALID_REQUEST", "request validation failed")

    @app.get("/instruments/search", operation_id="advisory_search_instruments")
    def search_instruments(
        request: Request,
        keyword: Annotated[str, Query(min_length=1, max_length=64)],
        limit: Annotated[int, Query(ge=1, le=20)] = 10,
    ) -> JSONResponse:
        value = provider.search_instruments(keyword.strip(), limit)
        return _response(request, status_code=200, data=_project("instrument_search", value))

    @app.get("/watchlist/quotes", operation_id="advisory_watchlist_quotes")
    def watchlist_quotes(
        request: Request,
        symbols: Annotated[list[str], Query(min_length=1, max_length=12)],
    ) -> JSONResponse:
        if not 1 <= len(symbols) <= 12:
            raise ValueError("watchlist size is outside the advisory contract")
        values = [str(SymbolId.parse(value)) for value in symbols]
        value = provider.watchlist_quotes(values)
        return _response(request, status_code=200, data=_project("watchlist_quotes", value))

    @app.get("/market/overview", operation_id="advisory_market_overview")
    def market_overview(request: Request) -> JSONResponse:
        value = provider.market_overview()
        return _response(request, status_code=200, data=_project("market_overview", value))

    @app.get("/symbols/{symbol}/analysis", operation_id="advisory_symbol_analysis")
    def symbol_analysis(
        request: Request,
        symbol: Annotated[str, Path(pattern=SAFE_SYMBOL)],
        period: Literal["day", "week"] = "day",
    ) -> JSONResponse:
        value = provider.symbol_analysis(str(SymbolId.parse(symbol)), period)
        return _response(request, status_code=200, data=_project("analysis", value))

    @app.get("/symbols/{symbol}/minute", operation_id="advisory_symbol_minute")
    def symbol_minute(
        request: Request,
        symbol: Annotated[str, Path(pattern=SAFE_SYMBOL)],
    ) -> JSONResponse:
        value = provider.symbol_minute(str(SymbolId.parse(symbol)))
        return _response(request, status_code=200, data=_project("minute", value))

    @app.get("/reports", operation_id="advisory_list_reports")
    def list_reports(
        request: Request,
        subject: Annotated[str | None, Query(pattern=SAFE_SUBJECT)] = None,
        limit: Annotated[int, Query(ge=1, le=80)] = 30,
    ) -> JSONResponse:
        normalized_subject = (
            "WATCH"
            if subject == "WATCH"
            else str(SymbolId.parse(subject))
            if subject is not None
            else None
        )
        value = provider.list_reports(normalized_subject, limit)
        return _response(request, status_code=200, data=_project("reports", value))

    @app.get("/reports/{report_id}", operation_id="advisory_get_report")
    def get_report(
        request: Request,
        report_id: Annotated[
            str,
            Path(min_length=1, max_length=128, pattern=SAFE_REPORT_ID),
        ],
    ) -> JSONResponse:
        ReportId.parse(report_id)
        value = provider.get_report(report_id)
        if value is None:
            return _error(request, 404, "REPORT_NOT_FOUND", "report was not found")
        return _response(request, status_code=200, data=_project("report", value))

    return app


__all__ = ["ADVISORY_BOUNDARY", "AdvisoryServiceProvider", "create_advisory_app"]
