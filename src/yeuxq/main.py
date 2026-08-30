"""yeuxQ application entry point."""

from __future__ import annotations

import webbrowser
from threading import Timer

import uvicorn

from yeuxq.security import RuntimeSecrets, ServeMode, validate_serve_security
from yeuxq.settings import get_settings


def main() -> None:
    settings = get_settings()
    runtime_secrets = RuntimeSecrets.from_env()
    host = settings.app.host
    port = settings.app.port
    certfile = (
        settings.resolve_file_path(settings.app.tls_certfile) if settings.app.tls_certfile else None
    )
    keyfile = (
        settings.resolve_file_path(settings.app.tls_keyfile) if settings.app.tls_keyfile else None
    )
    security = validate_serve_security(
        host=host,
        access_token=runtime_secrets.access_token,
        allowed_hosts=settings.app.allowed_hosts,
        tls_certfile=certfile,
        tls_keyfile=keyfile,
    )
    display_host = host
    if security.mode is ServeMode.NETWORK:
        display_host = security.allowed_hosts[0]
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    scheme = "https" if security.tls_enabled else "http"
    url = f"{scheme}://{display_host}:{port}/"

    def _open():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # 网络模式可能使用远端主机名或受信证书，不自动打开本机浏览器。
    if security.mode is ServeMode.LOOPBACK:
        Timer(1.5, _open).start()
    print("=" * 56)
    print(f"  {settings.app.name} v{settings.app.version}")
    print(f"  看板: {url}")
    print(f"  API 文档: {url}docs")
    print(f"  示例: {url}api/analyze?symbol=600519")
    print("=" * 56)
    uvicorn.run(
        "yeuxq.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
        reload=False,
        ssl_certfile=str(certfile) if certfile else None,
        ssl_keyfile=str(keyfile) if keyfile else None,
    )


if __name__ == "__main__":
    main()
