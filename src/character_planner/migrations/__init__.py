"""Alembic schema migrations (#60, ADR 0022). Revisions are in versions/.

Add one after changing a table in db.py:

    uv run alembic revision --autogenerate -m "Add a column to WeightPreset"

then read the generated file, fix what autogenerate can't know (renames, data moves), and
commit it with the model change. tests/test_migrations.py fails until models and
migrations agree.
"""
