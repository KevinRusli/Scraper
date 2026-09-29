from lead_scraper.enrich import _clean_emails, _pick


def test_clean_emails_filters_junk():
    html = 'mail info@biz.co.id or <img src="logo@2x.png"> sentry@sentry.io user@example.com INFO@biz.co.id'
    assert _clean_emails(html) == ["info@biz.co.id"]


def test_pick_prefers_own_domain():
    emails = ["someone@gmail.com", "sales@biz.co.id"]
    assert _pick(emails, "https://www.biz.co.id") == "sales@biz.co.id"
    assert _pick(["a@gmail.com"], "biz.co.id") == "a@gmail.com"
    assert _pick([], "biz.co.id") is None
