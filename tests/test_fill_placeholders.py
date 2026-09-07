from app.templates.engine import fill_placeholders


def test_slide_title_is_escaped():
    html = fill_placeholders(
        "<h1>{{title}}</h1>",
        {"title": "</h1><script>alert(1)</script>"},
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_non_http_image_url_dropped():
    html = fill_placeholders(
        '<img src="{{image_url}}">',
        {"image_url": "javascript:alert(1)"},
    )
    assert "javascript:" not in html
