"""Unit tests for the deterministic logic in the WAT tools.

These cover the pure functions — change detection, inline-markdown rendering,
and JSON extraction — that the workflow's reliability depends on. No network or
API calls are made.
"""
import analyze_competitors as analyze
import discover_competitors as discover
import monitor_competitors as mon
import pytest
import render_pdf_report as render
import scrape_site_pages as sp
import util


class TestSlugify:
    def test_strips_scheme_and_lowercases(self):
        assert mon.slugify("https://www.Example.com/Pricing") == "www-example-com-pricing"

    def test_short_host(self):
        assert mon.slugify("http://x.io") == "x-io"


class TestPriceTokens:
    def test_extracts_currency_and_percent(self):
        toks = mon.price_tokens("Plans from $20/mo, save 30% vs $200/yr")
        assert "$20" in toks
        assert "$200" in toks
        assert "30%" in toks

    def test_none_safe(self):
        assert mon.price_tokens("") == []


class TestDiffAgainstBaseline:
    def _snap(self, title, text):
        return {"title": title, "text": text, "prices": mon.price_tokens(text)}

    def test_identical_is_no_change(self):
        snap = self._snap("Pricing", "Plans start at $20 per month.")
        assert mon.diff_against_baseline(snap, dict(snap)) == []

    def test_price_change_detected(self):
        old = self._snap("Pricing", "Plans start at $20 per month.")
        new = self._snap("Pricing", "Plans start at $29 per month.")
        assert any("Pricing" in c for c in mon.diff_against_baseline(old, new))

    def test_title_change_detected(self):
        old = self._snap("Old title", "the body is the same here")
        new = self._snap("New title", "the body is the same here")
        assert any("Title" in c for c in mon.diff_against_baseline(old, new))

    def test_major_body_change_detected(self):
        old = self._snap("T", "alpha beta gamma delta " * 20)
        new = self._snap("T", "completely different wording throughout " * 20)
        assert any("Body content" in c for c in mon.diff_against_baseline(old, new))

    def test_trivial_whitespace_is_ignored(self):
        old = self._snap("T", "one two three four five")
        new = self._snap("T", "one   two  three   four five")
        assert mon.diff_against_baseline(old, new) == []


class TestMdInline:
    def test_bold_to_strong(self):
        assert str(render.md_inline("**hi**")) == "<strong>hi</strong>"

    def test_html_is_escaped(self):
        out = str(render.md_inline("a < b & c"))
        assert "&lt;" in out and "&amp;" in out

    def test_plain_passes_through(self):
        assert str(render.md_inline("plain text")) == "plain text"

    def test_none_safe(self):
        assert str(render.md_inline(None)) == ""


class TestExtractJson:
    def test_plain_object(self):
        assert analyze.extract_json('{"a": 1}') == {"a": 1}

    def test_strips_code_fences(self):
        assert analyze.extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_ignores_surrounding_prose(self):
        assert analyze.extract_json("Here you go:\n{\"a\": 1}\nThanks!") == {"a": 1}

    def test_raises_without_json(self):
        with pytest.raises(ValueError):
            analyze.extract_json("there is no json here")


class TestDiscover:
    def test_extract_array_plain(self):
        assert discover.extract_json_array('[{"url": "https://a.com"}]') == [{"url": "https://a.com"}]

    def test_extract_array_fenced_and_prose(self):
        raw = 'Here are the competitors:\n```json\n[{"url": "https://a.com"}]\n```'
        assert discover.extract_json_array(raw) == [{"url": "https://a.com"}]

    def test_extract_array_raises_without_array(self):
        with pytest.raises(ValueError):
            discover.extract_json_array("no array here")

    def test_normalize_dedupes_and_filters(self):
        items = [
            {"name": "A", "url": "https://a.com", "why": "x"},
            {"name": "A dup", "url": "https://a.com", "why": "y"},  # duplicate URL
            {"name": "No scheme", "url": "ftp://b.com"},            # non-http dropped
            {"name": "", "url": "https://c.com"},                   # name falls back to url
            "not a dict",                                            # ignored
        ]
        out = discover.normalize(items)
        assert [c["url"] for c in out] == ["https://a.com", "https://c.com"]
        assert out[1]["name"] == "https://c.com"


class TestUtilSlugify:
    def test_slug(self):
        assert util.slugify("https://www.Example.com/Page") == "www-example-com-page"

    def test_empty_fallback(self):
        assert util.slugify("https://") == "page"


class TestSelectKeyPages:
    def test_picks_key_same_domain_pages(self):
        base = "https://acme.com/"
        links = [
            "/pricing", "/about-us", "https://acme.com/product",
            "https://other.com/pricing", "/", "#top", "mailto:x@acme.com", "/blog/post-1",
        ]
        out = sp.select_key_pages(base, links, max_pages=5)
        assert "https://acme.com/pricing" in out
        assert "https://acme.com/about-us" in out
        assert "https://acme.com/product" in out
        assert all("other.com" not in u for u in out)   # external excluded
        assert "https://acme.com/" not in out            # homepage excluded
        assert all("/blog/" not in u for u in out)       # non-key path excluded

    def test_respects_max_pages(self):
        base = "https://acme.com/"
        links = ["/pricing", "/about", "/features", "/solutions", "/services"]
        assert len(sp.select_key_pages(base, links, max_pages=2)) == 2


class TestBuildCssVars:
    def test_emits_color_radius_and_font_vars(self):
        brand = {
            "colors": {"ink": "#0D0D0D", "jade_deep": "#3D6E5C"},
            "radius": {"sm": "6px"},
            "fonts": {"sans": {"stack": "GS"}, "serif": {"stack": "Lora"}},
        }
        css = render.build_css_vars(brand)
        assert "--ink: #0D0D0D;" in css
        assert "--jade-deep: #3D6E5C;" in css
        assert "--radius-sm: 6px;" in css
        assert "--font-sans: GS;" in css
        assert "--font-serif: Lora;" in css
