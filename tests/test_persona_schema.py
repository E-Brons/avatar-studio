"""Tests for PersonaSchema loading and validation."""


from pipeline.persona.schema import get_schema


class TestPersonaSchema:
    def setup_method(self):
        self.schema = get_schema()

    def test_loads_attributes(self):
        attrs = self.schema.attributes
        assert len(attrs) > 0

    def test_gender_present(self):
        assert "gender" in self.schema

    def test_age_present(self):
        assert "age" in self.schema

    def test_hair_style_present(self):
        assert "HAIR_STYLE" in self.schema

    def test_valid_selector_types_non_empty(self):
        types = self.schema.valid_selector_types("gender")
        assert len(types) > 0

    def test_default_selector_set(self):
        ds = self.schema.default_selector("gender")
        assert ds is not None
        assert isinstance(ds, str)

    def test_default_value_set(self):
        dv = self.schema.default_value("age")
        assert dv is not None

    def test_unknown_key_not_in_schema(self):
        assert "nonexistent_key_xyz" not in self.schema

    def test_get_returns_none_for_unknown(self):
        assert self.schema.get("nonexistent_key_xyz") is None

    def test_keys_returns_list(self):
        keys = self.schema.keys()
        assert isinstance(keys, list)
        assert "gender" in keys
