from src import input_parser


def test_load_any_parses_xml_with_attributes_and_repeated_tags(tmp_path):
    p = tmp_path / "sample.xml"
    p.write_text('<root attr="1"><child>value</child><child>value2</child></root>', encoding="utf-8")

    result = input_parser.load_any(p)

    assert result["format"] == "xml"
    assert result["data"]["root"]["@attr"] == "1"
    assert result["data"]["root"]["child"] == ["value", "value2"]
    assert result["path"] == str(p)


def test_load_any_parses_json(tmp_path):
    p = tmp_path / "sample.json"
    p.write_text('{"a": 1, "b": "two"}', encoding="utf-8")

    result = input_parser.load_any(p)

    assert result["format"] == "json"
    assert result["data"] == {"a": 1, "b": "two"}


def test_load_any_falls_back_to_raw_text_when_neither_xml_nor_json(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("not xml, not json, just text", encoding="utf-8")

    result = input_parser.load_any(p)

    assert result["format"] == "text"
    assert result["data"] == "not xml, not json, just text"


def test_load_any_decodes_latin1_bds_export_with_umlauts(tmp_path):
    # Real Baramundi .bds exports are often ISO-8859-1 with German text and
    # declare it via the <?xml encoding=...?> header - ElementTree needs
    # that declaration to know how to decode non-UTF-8 bytes.
    p = tmp_path / "sample.bds"
    xml_declaration = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<root>Grösse</root>'
    p.write_bytes(xml_declaration.encode("latin-1"))

    result = input_parser.load_any(p)

    assert result["format"] == "xml"
    assert result["data"]["root"] == "Grösse"


def test_load_any_falls_back_to_text_for_non_utf8_bytes_without_xml_declaration(tmp_path):
    # Without an explicit encoding declaration, ElementTree can't parse
    # non-UTF-8 bytes as XML - load_any should still return something
    # usable (raw decoded text) rather than raising.
    p = tmp_path / "no_declaration.bds"
    p.write_bytes('<root>Grösse</root>'.encode("latin-1"))

    result = input_parser.load_any(p)

    assert result["format"] == "text"
    assert result["data"] == "<root>Grösse</root>"


def test_element_to_dict_leaf_with_no_attributes_collapses_to_text():
    import xml.etree.ElementTree as ET

    el = ET.fromstring("<leaf>hello</leaf>")
    assert input_parser._element_to_dict(el) == "hello"


def test_element_to_dict_empty_leaf_collapses_to_none():
    import xml.etree.ElementTree as ET

    el = ET.fromstring("<leaf></leaf>")
    assert input_parser._element_to_dict(el) is None


def test_decode_prefers_utf8_when_valid():
    raw = "café".encode("utf-8")
    assert input_parser._decode(raw) == "café"


def test_decode_falls_back_to_latin1_for_non_utf8_bytes():
    raw = "caf\xe9".encode("latin-1")  # 0xE9 alone is not valid UTF-8
    assert input_parser._decode(raw) == "caf\xe9"
