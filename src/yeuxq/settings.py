"""yeuxQ public configuration and wheel-safe runtime paths."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator

from yeuxq.security import reject_sensitive_public_config


PACKAGE_ROOT = Path(__file__).resolve().parent


def _detect_project_root(package_root: Path = PACKAGE_ROOT) -> Path | None:
    """Return the source checkout root, never an arbitrary wheel parent."""

    source_dir = package_root.parent
    candidate = source_dir.parent
    if source_dir.name == "src" and (candidate / "pyproject.toml").is_file():
        return candidate.resolve()
    return None


PROJECT_ROOT = _detect_project_root()


def _absolute_from_cwd(value: str | os.PathLike[str]) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def default_runtime_data_root() -> Path:
    explicit = os.environ.get("YEUXQ_DATA_DIR")
    if explicit is not None:
        if not explicit.strip():
            raise ValueError("YEUXQ_DATA_DIR must not be empty")
        return _absolute_from_cwd(explicit)
    if PROJECT_ROOT is not None:
        return (PROJECT_ROOT / "data").resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return (base.expanduser() / "yeuxQ").resolve()


RUNTIME_DATA_ROOT = default_runtime_data_root()


class AppCfg(BaseModel):
    name: str = "yeuxQ"
    version: str = "2.0.0"
    host: str = "127.0.0.1"
    port: int = Field(8795, ge=1, le=65535)
    allowed_hosts: list[str] = Field(default_factory=list)
    tls_certfile: str | None = None
    tls_keyfile: str | None = None


class EngineWeights(BaseModel):
    trend: float = 0.25
    momentum: float = 0.20
    breakout: float = 0.20
    volume_price: float = 0.20
    pattern: float = 0.15


class ActionThresholds(BaseModel):
    strong_buy_score: int = 75
    strong_buy_confidence: int = 60
    strong_buy_modules: int = 4
    buy_score: int = 65
    buy_confidence: int = 45
    buy_modules: int = 3
    cautious_score: int = 60


class EngineCfg(BaseModel):
    weights: EngineWeights = Field(default_factory=EngineWeights)
    action: ActionThresholds = Field(default_factory=ActionThresholds)
    stop_loss: str = "hybrid"
    fixed_stop_pct: float = 0.05
    chanlun_bonus: bool = False
    sell_symmetric: bool = True
    atr_position: bool = True


class PredictionCfg(BaseModel):
    horizon_days: Literal[5] = 5
    bias: float = -0.2
    coeffs: dict[str, float] = Field(
        default_factory=lambda: {
            "score": 0.035,
            "trend": 0.008,
            "momentum": 0.006,
            "volume_price": 0.005,
            "breakout": 0.004,
            "m_score": 0.006,
            "main_flow_streak": 0.04,
        }
    )


class DataCfg(BaseModel):
    request_timeout: float = 8.0
    memory_ttl_seconds: float = 15.0
    quote_ttl_seconds: float = 2.0
    rate_limit_per_second: float = 8.0
    kline_store: str = "kline.db"
    tencent_kline: str = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    sina_kline: str = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    search_host: str = "https://searchapi.eastmoney.com"
    quote_hosts: list[str] = Field(
        default_factory=lambda: [
            "https://push2delay.eastmoney.com",
            "https://push2.eastmoney.com",
            "https://push2test.eastmoney.com",
        ]
    )
    his_hosts: list[str] = Field(
        default_factory=lambda: [
            "https://push2test.eastmoney.com",
            "https://push2his.eastmoney.com",
            "https://82.push2his.eastmoney.com",
            "https://90.push2his.eastmoney.com",
            "https://push2delay.eastmoney.com",
        ]
    )
    rt_flow_hosts: list[str] = Field(
        default_factory=lambda: [
            "https://push2delay.eastmoney.com",
            "https://push2.eastmoney.com",
        ]
    )


class ScanCfg(BaseModel):
    allow_full_market: bool = False
    max_workers: int = 6
    max_symbols: int = 200
    default_pool: list[str] = Field(
        default_factory=lambda: [
            "600519",
            "000001",
            "601318",
            "300750",
            "600036",
            "000858",
        ]
    )


class RiskCfg(BaseModel):
    hard_veto: list[str] = Field(
        default_factory=lambda: ["跌破MA20", "价跌量增", "OBV下降", "OBV走低", "OBV下行"]
    )
    soft_veto: list[str] = Field(default_factory=lambda: ["MA20向下", "MA20下行", "受压60日"])


class ResearchCfg(BaseModel):
    """Advisory report retention and public provider endpoints."""

    ttl_hours: float = 24.0
    replace_same_kind: bool = True
    max_brief_symbols: int = 8
    report_dir: str = "reports"
    max_report_bytes: int = 2 * 1024 * 1024
    llm_base_url: str = "https://grok.yeuxark.com/v1"
    llm_model: str = "grok-4.6"
    llm_reasoning_effort: str = "xhigh"
    llm_timeout: float = 240.0
    yeux_mcp_url: str = "https://search.yeuxark.com/mcp"
    yeux_timeout: float = 360.0


class Settings(BaseModel):
    host: str | None = None
    port: int | None = None
    data_dir: Path = Field(default_factory=default_runtime_data_root, exclude=True)

    app: AppCfg = Field(default_factory=AppCfg)
    engine: EngineCfg = Field(default_factory=EngineCfg)
    prediction: PredictionCfg = Field(default_factory=PredictionCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    scan: ScanCfg = Field(default_factory=ScanCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    research: ResearchCfg = Field(default_factory=ResearchCfg)

    _config_path: Path | None = PrivateAttr(default=None)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _validate_data_dir(cls, value: object) -> Path:
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            raise ValueError("data_dir must be a non-empty path")
        return _absolute_from_cwd(value)

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def runtime_data_root(self) -> Path:
        return self.data_dir

    def resolve_data_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        root = self.runtime_data_root.resolve()
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("relative data paths must remain under YEUXQ_DATA_DIR") from exc
        return resolved

    def resolve_file_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        if self._config_path is not None:
            return (self._config_path.parent / candidate).resolve()
        base = PROJECT_ROOT or Path.cwd()
        return (base / candidate).resolve()


def resolve_explicit_config(
    value: str | os.PathLike[str],
    *,
    cwd: Path | None = None,
    project_root: Path | None = PROJECT_ROOT,
) -> Path:
    raw = str(value)
    if not raw.strip():
        raise ValueError("YEUXQ_CONFIG must not be empty")
    candidate = Path(raw).expanduser()
    candidates: list[Path]
    if candidate.is_absolute():
        candidates = [candidate]
    else:
        candidates = [(cwd or Path.cwd()) / candidate]
        if project_root is not None:
            project_candidate = project_root / candidate
            if project_candidate not in candidates:
                candidates.append(project_candidate)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    searched = ", ".join(str(path.resolve()) for path in candidates)
    raise FileNotFoundError(f"YEUXQ_CONFIG does not reference a file; searched: {searched}")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("public configuration must be a YAML object")
    reject_sensitive_public_config(data)
    return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    explicit_config = os.environ.get("YEUXQ_CONFIG")
    config_path = resolve_explicit_config(explicit_config) if explicit_config is not None else None
    raw = load_yaml(config_path) if config_path is not None else {}
    settings = Settings(**raw)
    settings._config_path = config_path

    # These flat variables are the stable CLI deployment interface. Reading
    # them explicitly prevents YEUXQ_ENGINE from colliding with EngineCfg.
    configured_host = os.environ.get("YEUXQ_HOST") or settings.host
    configured_port = os.environ.get("YEUXQ_PORT")
    if configured_host:
        settings.app.host = configured_host
    if configured_port is not None:
        settings.app.port = AppCfg(port=configured_port).port
    elif settings.port is not None:
        settings.app.port = AppCfg(port=settings.port).port
    explicit_data_dir = os.environ.get("YEUXQ_DATA_DIR")
    if explicit_data_dir is not None:
        settings.data_dir = _absolute_from_cwd(explicit_data_dir)
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


__all__ = [
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "RUNTIME_DATA_ROOT",
    "Settings",
    "default_runtime_data_root",
    "get_settings",
    "load_yaml",
    "reload_settings",
    "resolve_explicit_config",
]
