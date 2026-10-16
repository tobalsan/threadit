import os

import uvicorn

from threaddit.app import create_app


def main() -> None:
    app = create_app(os.environ.get("THREADDIT_DB", "threaddit.db"))
    uvicorn.run(
        app,
        host=os.environ.get("THREADDIT_HOST", "127.0.0.1"),
        port=int(os.environ.get("THREADDIT_PORT", "8000")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
