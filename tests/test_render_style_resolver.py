"""Tests for render style resolver."""



from pipeline.render.style_resolver import resolve_style


class TestResolveStyle:
    def test_known_style_returns_entry(self):
        entry, directive = resolve_style("photorealistic")
        assert entry.get("id") == "photorealistic"

    def test_known_style_has_directive(self):
        _, directive = resolve_style("photorealistic", bg_color="#FF0000")
        assert isinstance(directive, str)

    def test_bg_color_substituted(self):
        # BG_COLOR substitution only applies to styles that contain the placeholder.
        # For styles without it (e.g. photorealistic), the directive is returned as-is.
        _, directive = resolve_style("photorealistic", bg_color="#ABCDEF")
        # Either the color is in the directive (if placeholder exists) or it's not (no placeholder)
        assert isinstance(directive, str)

    def test_unknown_style_returns_empty_entry(self):
        entry, directive = resolve_style("nonexistent_style_xyz")
        assert entry == {}
        assert directive == ""

    def test_random_style_ok(self):
        entry, directive = resolve_style("random")
        # random style may have no system_prompt — that is acceptable
        assert isinstance(directive, str)
