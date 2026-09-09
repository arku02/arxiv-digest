"""讓 `python -m arxiv_digest` 可以直接執行。"""

from arxiv_digest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
