# Build Order

1. Maintain and validate the foundation: API, configuration, database migrations,
   logging, tests, Docker, and CI.
2. Define security gates, identity, and authorization boundaries before device work.
3. Introduce the first narrow domain model and migration only after its requirements
   and audit needs are agreed.
4. Design the agent protocol before implementing Go agents.
5. Add mobile capabilities only after the API and trust model are stable.
