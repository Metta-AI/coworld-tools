from __future__ import annotations

from commissioners.common.commissioners import BaselineCommissioner
from commissioners.common.server import create_app

app = create_app(BaselineCommissioner())


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
