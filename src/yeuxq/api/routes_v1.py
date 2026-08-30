"""Versioned, read-only-by-default API contract for the integrated application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
import re
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from yeuxq.contracts import ContractValidationError, SymbolId, TrendObservation
from yeuxq.observation_store import ObservationStoreError
from yeuxq.services.integration_status import (
    blocked_integration_status,
    project_integration_status,
)
from yeuxq.services.observation import ObservationBuildError
from yeuxq.services.research_facade import (
    InvalidRunIdError,
    ResearchFacadeError,
    UnsafeResearchPathError,
)


log = logging.getLogger("yeuxq.api.v1")

API_PREFIX = "/api/v1"
MAX_LIST_LIMIT = 100
MAX_LIST_OFFSET = 10_000
SAFE_OBSERVATION_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SAFE_RUN_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
_SAFE_OBSERVATION_ID = re.compile(SAFE_OBSERVATION_ID)
_SAFE_RUN_ID = re.compile(SAFE_RUN_ID)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_READINESS = {"PASS", "WATCH", "BLOCK"}

ADVISORY_BOUNDARY: dict[str, object] = {
    "mode": "research_only_advisory_only",
    "prohibited_live_use": True,
    "broker_access": False,
    "live_trading_allowed": False,
}


class V1ServiceProvider(Protocol):
    """Only the capabilities exposed by the v1 router."""

    def get_integration_status(self) -> Mapping[str, Any]: ...

    def capture_observation(
        self, symbol: str, period: str
    ) -> TrendObservation | Mapping[str, Any]: ...

    def list_observations(
        self, *, limit: int, offset: int
    ) -> Sequence[TrendObservation | Mapping[str, Any]]: ...

    def get_observation(
        self, observation_id: str
    ) -> TrendObservation | Mapping[str, Any] | None: ...

    def list_research_runs(self, *, limit: int) -> Sequence[str]: ...

    def get_research_readiness(self, run_id: str) -> Mapping[str, Any]: ...


class CaptureObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str = Field(min_length=6, max_length=16)
    period: Literal["day", "week", "month"] = "day"

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        try:
            return str(SymbolId.parse(value))
        except ContractValidationError as exc:
            raise ValueError("symbol must be a mainland six-digit security identifier") from exc


class _ApiFailure(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    if _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _boundary() -> dict[str, object]:
    return dict(ADVISORY_BOUNDARY)


def _success(request: Request, data: object, *, status_code: int = 200) -> JSONResponse:
    request_id = request.state.yeuxq_request_id
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"request_id": request_id, "data": data, "advisory": _boundary()}),
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


def _error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    request_id = request.state.yeuxq_request_id
    payload: dict[str, object] = {
        "request_id": request_id,
        "error": {"code": code, "message": message},
        "advisory": _boundary(),
    }
    if details:
        payload["error"] = {"code": code, "message": message, "details": details}
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for item in exc.errors()[:16]:
        location = ".".join(str(part) for part in item.get("loc", ()))
        details.append({"location": location, "type": str(item.get("type", "invalid"))[:128]})
    return details


class _V1ContractRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original = super().get_route_handler()

        async def contract_handler(request: Request):  # type: ignore[no-untyped-def]
            request.state.yeuxq_request_id = _request_id(request)
            try:
                response = await original(request)
            except RequestValidationError as exc:
                return _error(
                    request,
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="request validation failed",
                    details=_validation_details(exc),
                )
            except _ApiFailure as exc:
                return _error(
                    request,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )
            except (InvalidRunIdError, UnsafeResearchPathError, ObservationBuildError, ValueError):
                return _error(
                    request,
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="request was rejected by the service contract",
                )
            except (ObservationStoreError, ResearchFacadeError):
                return _error(
                    request,
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="the requested local service is unavailable",
                )
            except HTTPException as exc:
                return _error(
                    request,
                    status_code=exc.status_code,
                    code="HTTP_ERROR",
                    message="request could not be completed",
                )
            except Exception:
                log.exception(
                    "unhandled v1 service failure",
                    extra={"request_id": request.state.yeuxq_request_id},
                )
                return _error(
                    request,
                    status_code=503,
                    code="SERVICE_UNAVAILABLE",
                    message="the requested local service is unavailable",
                )
            response.headers["X-Request-ID"] = request.state.yeuxq_request_id
            response.headers["Cache-Control"] = "no-store"
            return response

        return contract_handler


def _observation_payload(value: TrendObservation | Mapping[str, Any]) -> dict[str, Any]:
    payload = value.to_dict() if isinstance(value, TrendObservation) else dict(value)
    if (
        payload.get("prohibited_live_use") is not True
        or payload.get("broker_access") is not False
        or payload.get("live_trading_allowed") is not False
    ):
        raise _ApiFailure(
            503, "SERVICE_CONTRACT_VIOLATION", "observation safety fields are invalid"
        )
    observation_id = payload.get("observation_id")
    if (
        not isinstance(observation_id, str)
        or _SAFE_OBSERVATION_ID.fullmatch(observation_id) is None
    ):
        raise _ApiFailure(503, "SERVICE_CONTRACT_VIOLATION", "observation identifier is invalid")
    return payload


def _status_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if {"valid", "release_readiness", "reason", "status"} <= set(value):
        if value.get("valid") is not True:
            return blocked_integration_status(str(value.get("reason") or "STATUS_INVALID"))
        projection = project_integration_status(value.get("status"))
    else:
        projection = project_integration_status(value)
    if projection.get("valid") is not True:
        return projection
    return projection


def _readiness_payload(value: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    payload = dict(value)
    if (
        payload.get("run_id") != run_id
        or payload.get("decision") not in _READINESS
        or payload.get("read_only") is not True
        or payload.get("broker_access") is not False
        or payload.get("live_trading_allowed") is not False
    ):
        raise _ApiFailure(503, "SERVICE_CONTRACT_VIOLATION", "readiness projection is invalid")
    return payload


def _safe_run_ids(values: Sequence[str], limit: int) -> list[str]:
    if isinstance(values, (str, bytes, bytearray)):
        raise _ApiFailure(503, "SERVICE_CONTRACT_VIOLATION", "research run list is invalid")
    result: list[str] = []
    for value in values[:limit]:
        if not isinstance(value, str) or _SAFE_RUN_ID.fullmatch(value) is None:
            raise _ApiFailure(503, "SERVICE_CONTRACT_VIOLATION", "research run id is invalid")
        result.append(value)
    return result


def create_v1_router(service_provider: V1ServiceProvider) -> APIRouter:
    """Create the v1 router without importing the application container."""

    router = APIRouter(prefix=API_PREFIX, tags=["v1"], route_class=_V1ContractRoute)

    @router.get("/health", operation_id="v1_health")
    def health(request: Request) -> JSONResponse:
        return _success(request, {"status": "ok", "api_version": "v1"})

    @router.get("/integration/status", operation_id="v1_integration_status")
    def integration_status(request: Request) -> JSONResponse:
        return _success(request, _status_payload(service_provider.get_integration_status()))

    @router.post("/observations/capture", operation_id="v1_capture_observation")
    def capture_observation(request: Request, payload: CaptureObservationRequest) -> JSONResponse:
        captured = service_provider.capture_observation(payload.symbol, payload.period)
        return _success(request, _observation_payload(captured), status_code=201)

    @router.get("/observations", operation_id="v1_list_observations")
    def list_observations(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
        offset: Annotated[int, Query(ge=0, le=MAX_LIST_OFFSET)] = 0,
    ) -> JSONResponse:
        values = service_provider.list_observations(limit=limit, offset=offset)
        if isinstance(values, (str, bytes, bytearray)):
            raise _ApiFailure(503, "SERVICE_CONTRACT_VIOLATION", "observation list is invalid")
        items = [_observation_payload(value) for value in values[:limit]]
        return _success(
            request,
            {"items": items, "count": len(items), "limit": limit, "offset": offset},
        )

    @router.get("/observations/{observation_id}", operation_id="v1_get_observation")
    def get_observation(
        request: Request,
        observation_id: Annotated[
            str,
            Path(min_length=1, max_length=128, pattern=SAFE_OBSERVATION_ID),
        ],
    ) -> JSONResponse:
        value = service_provider.get_observation(observation_id)
        if value is None:
            raise _ApiFailure(404, "OBSERVATION_NOT_FOUND", "observation was not found")
        return _success(request, _observation_payload(value))

    @router.get(
        "/observations/{unsafe_path:path}",
        include_in_schema=False,
        operation_id="v1_reject_unsafe_observation_path",
    )
    def reject_unsafe_observation_path(request: Request, unsafe_path: str) -> JSONResponse:
        raise _ApiFailure(422, "INVALID_REQUEST", "observation id contains an unsafe path")

    @router.get("/research/runs", operation_id="v1_list_research_runs")
    def list_research_runs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    ) -> JSONResponse:
        run_ids = _safe_run_ids(service_provider.list_research_runs(limit=limit), limit)
        return _success(request, {"items": run_ids, "count": len(run_ids), "limit": limit})

    @router.get("/research/readiness/{run_id}", operation_id="v1_get_research_readiness")
    def get_research_readiness(
        request: Request,
        run_id: Annotated[str, Path(min_length=1, max_length=128, pattern=SAFE_RUN_ID)],
    ) -> JSONResponse:
        return _success(
            request,
            _readiness_payload(service_provider.get_research_readiness(run_id), run_id),
        )

    @router.get(
        "/research/readiness/{unsafe_path:path}",
        include_in_schema=False,
        operation_id="v1_reject_unsafe_research_path",
    )
    def reject_unsafe_research_path(request: Request, unsafe_path: str) -> JSONResponse:
        raise _ApiFailure(422, "INVALID_REQUEST", "run id contains an unsafe path")

    return router


__all__ = [
    "ADVISORY_BOUNDARY",
    "API_PREFIX",
    "CaptureObservationRequest",
    "MAX_LIST_LIMIT",
    "V1ServiceProvider",
    "create_v1_router",
]
