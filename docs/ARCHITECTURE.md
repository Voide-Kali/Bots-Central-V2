# Architecture

Bots Central V2 starts as a modular monolith. The Python/FastAPI backend owns the
versioned HTTP API, business rules, persistence, and audit integration points.
PostgreSQL is the primary relational datastore.

Future Go agents will execute only explicitly authorized work on managed devices and
communicate through the backend API. A future Flutter mobile client will consume the
same public API. Agents and mobile clients must not access PostgreSQL directly.

The current backend has `api`, `core`, and `db` modules. No product-domain module,
agent protocol, authentication, or mobile code exists yet.
