# Build Analysis and Tracking Service (🦇 BATS 🦇)

This sub-project aims to provide structure for automated build analysis
and data storage that can be used to feed developer dashboards or other
investigative interfaces.

# Design

A database-backed web service with a helper CLI tool. The expected data flow is that
post-CI job run, a new run will be created in this service, and then test results
and optionally other resources can be uploaded.

# Running

## Development

`poetry run fastapi dev`

## Production

# Migrations

## Upgrades

```
poetry run alembic upgrade head
```

## Initialization

* Start with a clean database:

```
rm -f database.sql
```

* Initial alembic configuration:

```
poetry run alembic init --template pyproject alembic
```

* Update env.py:

```
import sqlmodel
import bats.models
target_metadata = sqlmodel.SQLModel.metadata
```

* Generate initial migration:

```
poetry run alembic revision --autogenerate -m 'Initial migration'
```

* Edit the migration to add missing import for `sqlmodel`
* Test that it works:

```
poetry run alembic upgrade head
```

* Confirm:

```
sqlite3 database.db -- .schema
```

# License

As this sub-project aims to provide a web service, it is licensed with AGPLv3.
