from src import splitter

MERGED_MD = """# Software Package
Adobe Acrobat Reader DC, version 26.001.21431.

## Purpose
Confirms the install completed successfully.

## Preconditions
- Windows 10/11
- Admin rights

## Validation Rules
- Verify button must be clickable.

## Evidence
- Screenshot of the confirmation screen.

## Aqua Test Case Mapping
- TC-001 -> install_confirmation_v1.html
"""


def test_split_into_three_maps_each_section_to_the_right_file():
    result = splitter.split_into_three(MERGED_MD)

    assert "Software Package" in result["readme"]
    assert "Purpose" in result["readme"]
    assert "Preconditions" in result["requirements"]
    assert "Validation Rules" in result["requirements"]
    assert "Evidence" in result["testspec"]
    assert "Aqua Test Case Mapping" in result["testspec"]


def test_split_into_three_keeps_readme_content_out_of_requirements():
    result = splitter.split_into_three(MERGED_MD)

    assert "Admin rights" not in result["readme"]
    assert "Adobe Acrobat Reader DC" not in result["requirements"]


def test_split_into_three_missing_sections_fall_back_to_placeholder():
    minimal_md = "# Software Package\nSome package.\n"

    result = splitter.split_into_three(minimal_md)

    assert "Some package." in result["readme"]
    assert result["requirements"] == "Not specified in source artifacts.\n"
    assert result["testspec"] == "Not specified in source artifacts.\n"


def test_split_into_three_handles_completely_unheaded_markdown():
    result = splitter.split_into_three("just some prose, no headings at all\n")

    assert result["readme"] == "Not specified in source artifacts.\n"
    assert result["requirements"] == "Not specified in source artifacts.\n"
    assert result["testspec"] == "Not specified in source artifacts.\n"
