import os

import uvicorn

from threadit.app import create_app


def main() -> None:
    app = create_app(os.environ.get("THREADIT_DB", "threadit.db"))
    uvicorn.run(
        app,
        host=os.environ.get("THREADIT_HOST", "127.0.0.1"),
        port=int(os.environ.get("THREADIT_PORT", "8000")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
