from __future__ import annotations

from pathlib import Path


REQUIRED_SECTIONS = [
    "## 这一章解决什么问题",
    "## 先用人话理解",
    "## 核心概念",
    "## 数学公式与推导",
    "## 放到 A 股量化里怎么用",
    "## 和本项目代码的对应关系",
    "## 常见误区",
    "## 本章练习",
    "## 读完检查清单",
    "## 参考链接",
]


def test_chapter_notes_follow_template() -> None:
    notes_root = Path("docs/notes")
    chapter_files = [
        *[p for p in sorted((notes_root / "fpp").glob("*.md")) if p.name != "deep_lecture.md"],
        *[p for p in sorted((notes_root / "factor").glob("*.md")) if p.name != "deep_lecture.md"],
        *sorted((notes_root / "math").glob("*.md")),
    ]
    assert len(chapter_files) >= 28
    for path in chapter_files:
        text = path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{path} missing {section}"


def test_notes_index_links_to_all_chapters() -> None:
    index = Path("docs/notes/README.md").read_text(encoding="utf-8")
    assert "历史回测" in index
    assert "不能保证未来收益" in index
    for path in Path("docs/notes").glob("*/*.md"):
        rel = path.relative_to(Path("docs/notes")).as_posix()
        assert rel in index or path.parent.name == "math", f"Missing index link for {rel}"


def test_deep_lectures_are_substantial() -> None:
    fpp = Path("docs/notes/fpp/deep_lecture.md").read_text(encoding="utf-8")
    factor = Path("docs/notes/factor/deep_lecture.md").read_text(encoding="utf-8")
    for text in (fpp, factor):
        assert len(text) > 6000
        assert "风险提示" in text
        assert "数学" in text or "公式" in text
        assert "项目" in text
        assert "```text" in text


def test_readme_links_notes_index() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    intro = Path("docs/00_从零开始.md").read_text(encoding="utf-8")
    assert "docs/notes/README.md" in readme
    assert "notes/README.md" in intro
