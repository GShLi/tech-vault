from backend.app.api.envelope import page_envelope


def test_page_envelope_reports_cursor_state_and_request_id():
    assert page_envelope(["item"], "req-page-1") == {
        "data": ["item"],
        "meta": {
            "next_cursor": None,
            "has_more": False,
            "request_id": "req-page-1",
        },
    }
    assert page_envelope([], "req-page-2", next_cursor="next-page") == {
        "data": [],
        "meta": {
            "next_cursor": "next-page",
            "has_more": True,
            "request_id": "req-page-2",
        },
    }
