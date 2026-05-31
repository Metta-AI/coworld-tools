from __future__ import annotations

from commissioners.common.commissioners import CogsVsClipsCommissioner
from commissioners.common.server import create_app

app = create_app(CogsVsClipsCommissioner())


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
