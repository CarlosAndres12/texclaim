import pytest

from texclaim.config import ConfigError
from texclaim.parser.root_finder import find_root

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_fixture_root(sample_paper):
    assert find_root(sample_paper).name == "main.tex"


def test_explicit_main_wins(tmp_path):
    w(tmp_path / "a.tex", DOC % "\\input{x}")
    w(tmp_path / "b.tex", DOC % "")
    assert find_root(tmp_path, "b.tex").name == "b.tex"


def test_magic_comment_most_common(tmp_path):
    w(tmp_path / "main.tex", DOC % "")
    w(tmp_path / "other.tex", DOC % "")
    w(tmp_path / "s1.tex", "% !TEX root = other.tex\ntext")
    w(tmp_path / "s2.tex", "% !TEX root = other.tex\ntext")
    assert find_root(tmp_path).name == "other.tex"


def test_latexmkrc(tmp_path):
    w(tmp_path / "a.tex", DOC % "")
    w(tmp_path / "b.tex", DOC % "")
    w(tmp_path / ".latexmkrc", "@default_files = ('b.tex');\n")
    assert find_root(tmp_path).name == "b.tex"


def test_ranking_prefers_includes_then_name(tmp_path):
    w(tmp_path / "notes.tex", DOC % "")
    w(tmp_path / "paper.tex", DOC % "")
    assert find_root(tmp_path).name == "paper.tex"
    w(tmp_path / "z.tex", DOC % "\\input{s}")
    assert find_root(tmp_path).name == "z.tex"


def test_standalone_and_comments_excluded(tmp_path):
    w(tmp_path / "fig.tex", "\\documentclass{standalone}\n\\begin{document}x\\end{document}")
    w(tmp_path / "old.tex", "% \\documentclass{article}\n% \\begin{document}\n")
    w(tmp_path / "real.tex", DOC % "")
    assert find_root(tmp_path).name == "real.tex"


def test_tie_is_refused(tmp_path):
    w(tmp_path / "a.tex", DOC % "")
    w(tmp_path / "b.tex", DOC % "")
    with pytest.raises(ConfigError, match="a.tex"):
        find_root(tmp_path)


def test_skips_build_dirs(tmp_path):
    w(tmp_path / "build" / "main.tex", DOC % "")
    with pytest.raises(ConfigError):
        find_root(tmp_path)
