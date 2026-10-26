"""Read-only Gmail provider and its wiring into the bot (ADR-024).

No google libraries and no database: a fake Gmail service drives the provider, and the
bot helpers are exercised with fakes. The google client is only imported lazily inside
``build_service`` (not under test here), so these run on the lean backend as-is.
"""

import base64
from typing import Any, cast

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.inbox import gmail_api
from app.inbox.inbox import MAX_SNIPPET_CHARS, EmailFilter, EmailMessage, EmailNotice
from app.telegram import bot


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class _Req:
    def __init__(self, value: dict[str, Any]) -> None:
        self._value = value

    def execute(self) -> dict[str, Any]:
        return self._value


class _FakeMessages:
    def __init__(self, pages: list[dict[str, Any]], details: dict[str, dict[str, Any]]) -> None:
        self._pages = list(pages)
        self._details = details
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Req:
        self.list_calls.append(kwargs)
        page = self._pages.pop(0) if self._pages else {"messages": []}
        return _Req(page)

    def get(self, *, userId: str, id: str, format: str) -> _Req:  # noqa: A002 - Gmail API name
        return _Req(self._details[id])


class _FakeService:
    def __init__(self, messages: _FakeMessages) -> None:
        self._messages = messages

    def users(self) -> "_FakeService":
        return self

    def messages(self) -> _FakeMessages:
        return self._messages


def _detail(message_id: str, sender: str, subject: str, body: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "snippet": "preview",
        "payload": {
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
            "parts": [{"mimeType": "text/plain", "body": {"data": _b64(body)}}],
        },
    }


def test_extract_body_prefers_plain_then_falls_back_to_html() -> None:
    plain = {"parts": [{"mimeType": "text/plain", "body": {"data": _b64("corpo puro")}}]}
    assert gmail_api.extract_body(plain) == "corpo puro"
    html_data = _b64("<p>Oi <b>mundo</b></p>")
    html_only = {"parts": [{"mimeType": "text/html", "body": {"data": html_data}}]}
    assert gmail_api.extract_body(html_only) == "Oi mundo"


def test_message_to_email_maps_headers_body_and_caps_snippet() -> None:
    long_body = "x" * (MAX_SNIPPET_CHARS + 50)
    message = gmail_api.message_to_email(_detail("m1", "Alice <a@x.com>", "Reuniao", long_body))
    assert message.message_id == "m1"
    assert message.sender == "Alice <a@x.com>" and message.subject == "Reuniao"
    assert len(message.snippet) == MAX_SNIPPET_CHARS


def test_list_unread_ids_pages_and_caps() -> None:
    pages: list[dict[str, Any]] = [
        {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "t"},
        {"messages": [{"id": "c"}]},
    ]
    service = _FakeService(_FakeMessages(pages, {}))
    assert gmail_api._list_unread_ids(service, max_results=5, scan_limit=100) == ["a", "b", "c"]
    capped = _FakeService(_FakeMessages([{"messages": [{"id": "a"}, {"id": "b"}]}], {}))
    assert gmail_api._list_unread_ids(capped, max_results=1, scan_limit=100) == ["a"]


def test_provider_fetches_and_maps_unread() -> None:
    details = {
        "a": _detail("a", "noreply@x.com", "Promo", "spam"),
        "b": _detail("b", "Chefe <chefe@x.com>", "Reuniao amanha", "as 9h"),
    }
    pages: list[dict[str, Any]] = [{"messages": [{"id": "a"}, {"id": "b"}]}]
    service = _FakeService(_FakeMessages(pages, details))
    provider = gmail_api.GmailApiProvider(
        token_file="/unused", service_builder=lambda _t, _s: service
    )
    messages = provider.fetch_recent("a@x.com")
    # The provider fetches everything; EmailFilter decides what is announced (checked below).
    assert [m.message_id for m in messages] == ["a", "b"]
    assert messages[1].subject == "Reuniao amanha" and messages[1].snippet == "as 9h"


def test_provider_swallows_errors_and_rebuilds_service() -> None:
    builds = {"count": 0}

    class _Boom:
        def users(self) -> "_Boom":
            return self

        def messages(self) -> "_Boom":
            return self

        def list(self, **_kwargs: Any) -> Any:
            raise RuntimeError("gmail down")

    def builder(_token: str, _timeout: int) -> Any:
        builds["count"] += 1
        return _Boom()

    provider = gmail_api.GmailApiProvider(token_file="/unused", service_builder=builder)
    assert provider.fetch_recent("a@x.com") == []
    assert provider._service is None  # dropped so the next pass rebuilds
    assert provider.fetch_recent("a@x.com") == []
    assert builds["count"] == 2


def test_assert_read_only_accepts_only_gmail_readonly() -> None:
    gmail_api.assert_read_only([gmail_api.READONLY_SCOPE])  # does not raise


def test_assert_read_only_refuses_broader_or_unknown_scopes() -> None:
    import pytest

    for bad in (
        None,
        [],
        ["https://mail.google.com/"],
        ["https://www.googleapis.com/auth/gmail.modify"],
        [gmail_api.READONLY_SCOPE, "https://www.googleapis.com/auth/gmail.send"],
    ):
        with pytest.raises(gmail_api.GmailUnavailable):
            gmail_api.assert_read_only(bad)


def test_email_filter_drops_noise_keeps_real_mail() -> None:
    email_filter = EmailFilter(
        ignore_sender_domains=("noreply", "newsletter"), ignore_subject_keywords=("promo",)
    )
    assert not email_filter.allows(EmailMessage("1", sender="noreply@x.com", subject="Oi"))
    assert not email_filter.allows(EmailMessage("2", sender="a@x.com", subject="Mega PROMO"))
    assert email_filter.allows(EmailMessage("3", sender="chefe@x.com", subject="Reuniao"))


def test_split_tokens_trims_and_drops_blanks() -> None:
    assert bot._split_tokens("noreply, newsletter ,, marketing") == (
        "noreply",
        "newsletter",
        "marketing",
    )
    assert bot._split_tokens("") == ()


def test_email_watch_is_off_until_fully_configured() -> None:
    settings = Settings(gmail_token_file=None, gmail_account=None, email_owner=None)
    assert bot._email_watch(settings, cast("sessionmaker[Session]", None)) is None


class _FakeProvider:
    def fetch_recent(self, account: str) -> list[EmailMessage]:
        return []


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str, keyboard: Any = None) -> None:
        self.sent.append((chat_id, text))


def test_deliver_emails_sends_one_message_per_notice(monkeypatch: Any) -> None:
    notices = [EmailNotice(chat_id=10, text="Novo e-mail de chefe@x.com: Reuniao")]
    monkeypatch.setattr(bot, "collect_email_notices", lambda *a, **k: notices)
    watch = bot.EmailWatch(provider=_FakeProvider(), targets=[], email_filter=EmailFilter())
    client = _FakeClient()
    bot._deliver_emails(cast(Any, client), cast(Any, None), None, watch)
    assert client.sent == [(10, "Novo e-mail de chefe@x.com: Reuniao")]
