from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_all_alembic_revision_identifiers_fit_version_table() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    script_directory = ScriptDirectory.from_config(config)

    revisions = list(script_directory.walk_revisions(base="base", head="heads"))

    assert revisions
    assert all(
        revision.revision is not None and len(revision.revision) <= 32 for revision in revisions
    )
    assert [revision.revision for revision in revisions] == [
        "0008_device_telemetry",
        "0007_pairing_revocation",
        "0006_device_online_v01",
        "0005_device_foundation",
        "0004_auth_abuse_control",
        "0003_email_challenge_foundation",
        "0002_auth_database_foundation",
        "0001_foundation",
    ]
    assert script_directory.get_current_head() == "0008_device_telemetry"
