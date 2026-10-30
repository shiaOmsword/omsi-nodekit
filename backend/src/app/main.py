import uvicorn

from app.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "app.create_app:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.log_level.lower(),
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
