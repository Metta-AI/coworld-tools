from __future__ import annotations

from commissioners.common.app import commissioner_app, run

app = commissioner_app("cogs_vs_clips")


def main() -> None:
    run(app)


if __name__ == "__main__":
    main()
