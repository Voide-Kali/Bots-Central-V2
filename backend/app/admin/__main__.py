"""Server-side role management (ADR-017). The web can never promote anyone.

docker compose exec backend python -m app.admin promote email@exemplo.com
docker compose exec backend python -m app.admin demote email@exemplo.com
"""

import sys

from sqlalchemy.orm import sessionmaker

from app.admin.service import set_role
from app.db.session import get_engine


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("promote", "demote"):
        print("uso: python -m app.admin promote|demote EMAIL", file=sys.stderr)
        return 2
    factory = sessionmaker(bind=get_engine())
    role = "admin" if argv[0] == "promote" else "user"
    if not set_role(factory, email=argv[1], role=role):
        print("nenhuma conta com esse e-mail", file=sys.stderr)
        return 1
    print(f"ok: {argv[1]} agora é {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
