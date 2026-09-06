# Backend

Run the backend from this directory. It deliberately has no product-domain models
or endpoints yet; the only public route is `GET /api/v1/health`.

## Reproducible dependencies

`requirements.lock` records the exact dependency set validated for this foundation.
Install it with `python -m pip install -r requirements.lock`. Update this file only
when intentionally updating dependencies, then run all quality checks and
`pip-audit`.
