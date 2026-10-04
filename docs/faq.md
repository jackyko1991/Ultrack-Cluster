# FAQ

**Can the database be reused across tracking stages, e.g. for a parameter sweep?**
Yes. Segmentation turns the labels into candidate segments stored in the database; later stages read them. A sweep over `[linking]` parameters can restart from link, and over `[tracking]` parameters from solve, by resuming the run (`SKIP_SEG=true`, and `SKIP_LINK=true` for solve only; see [Running](running.md#resuming)). Changes to `[segmentation]` need a new run. Clear the stage first with `ultrack clear_database -cfg <config> <stage>`: ultrack's `--overwrite` flag clears the database once per array task, which breaks distributed runs. `KEEP_DB=true` keeps the server running between sweep steps.

**Where is the database schema documented?**
In ultrack: [schema](https://github.com/royerlab/ultrack/blob/main/ultrack/core/README.md), [implementation](https://github.com/royerlab/ultrack/blob/main/ultrack/core/database.py). Ultrack accesses it through [SQLAlchemy](https://www.sqlalchemy.org/).

**When is PostgreSQL needed instead of SQLite?**
SQLite is ultrack's default and suits single-process runs ([`config_sqlite.toml`](../tracking/config_sqlite.toml)). It does not support many concurrent writers, so the distributed job arrays need PostgreSQL.

**The solve job ran out of memory or was slow on a large dataset.**
See [Solver settings](solver.md).
