from __future__ import annotations

import base64
from pathlib import Path

import pytest

from adcs.admin.howto_overrides import FileBackedHowToOverrideStore


@pytest.fixture()
def override_store(tmp_path: Path) -> FileBackedHowToOverrideStore:
    return FileBackedHowToOverrideStore(
        storage_path=tmp_path / "overrides.json",
        asset_dir=tmp_path / "assets",
    )


def test_howto_override_store_round_trip_and_publish(
    override_store: FileBackedHowToOverrideStore,
) -> None:
    payload = {
        "entry_label": {"en": "Health", "ru": "Состояние"},
        "title": {"en": "Health Ops", "ru": "Операции Health"},
        "summary": {"en": "Summary", "ru": "Сводка"},
        "purpose": {"en": ["Line 1"], "ru": ["Строка 1"]},
        "workflow": {"en": ["Step 1"], "ru": ["Шаг 1"]},
        "callouts": [
            {
                "id": "callout-1",
                "level": "warning",
                "title": {"en": "Stop", "ru": "Стоп"},
                "body": {"en": ["Check coverage"], "ru": ["Проверьте coverage"]},
            }
        ],
        "commands": [
            {
                "id": "command-1",
                "label": {"en": "Run gate", "ru": "Запустить gate"},
                "description": {"en": "Run QA", "ru": "Запустить QA"},
                "command": "make admin-ui-regression-gates",
            }
        ],
        "examples": [
            {
                "id": "example-1",
                "title": {"en": "Example", "ru": "Пример"},
                "bullets": {"en": ["Bullet 1"], "ru": ["Пункт 1"]},
            }
        ],
        "screenshots": [
            {
                "id": "shot-1",
                "src": "/v1/howto/assets/shot-1.png",
                "alt": {"en": "Alt", "ru": "Альт"},
                "caption": {"en": "Caption", "ru": "Подпись"},
            }
        ],
    }

    draft_record = override_store.upsert_draft(
        article_id="admin-health",
        payload=payload,
        actor_key_id="key-super",
    )

    assert draft_record.article_id == "admin-health"
    assert draft_record.draft is not None
    assert draft_record.draft.title.en == "Health Ops"
    assert draft_record.draft.examples[0].title.ru == "Пример"
    assert draft_record.published is None

    published_record = override_store.publish(
        article_id="admin-health",
        actor_key_id="key-super",
    )

    assert published_record.published is not None
    assert published_record.published.commands[0].command == "make admin-ui-regression-gates"
    assert published_record.published_updated_by == "key-super"

    stored = override_store.get_record("admin-health")
    assert stored.published is not None
    assert stored.published.examples[0].bullets.en == ("Bullet 1",)


def test_howto_override_store_asset_path_is_constrained(
    override_store: FileBackedHowToOverrideStore,
) -> None:
    asset_name = override_store.store_asset(
        filename="demo.png",
        content_base64=base64.b64encode(b"png-bytes").decode("ascii"),
    )

    resolved = override_store.resolve_asset_path(asset_name)
    assert resolved.exists()
    assert resolved.read_bytes() == b"png-bytes"

    with pytest.raises(ValueError):
        override_store.resolve_asset_path("../escape.txt")
