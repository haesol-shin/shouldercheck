import pytest

from shouldercheck.memory.tokens import Masker, tokenize


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("논문을", ["논문", "문을"]),
        ("논문", ["논문"]),
        ("논", ["논"]),
        ("논 문", ["논", "문"]),
        ("A논", ["a"]),
        ("Reviews tests class pass", ["review", "test", "class", "pass"]),
        ("PR-12 v2", ["pr", "12", "v2"]),
        ("漢字検索", ["漢字", "字検", "検索"]),
        ("カタカナ", ["カタ", "タカ", "カナ"]),
    ],
)
def test_tokens(text, tokens):
    assert tokenize(text) == tokens


def test_decomposed_hangul_matches_precomposed():
    assert tokenize("논문".encode().decode()) == tokenize("논문")


def test_particle_does_not_hide_the_stem():
    assert set(tokenize("논문")) <= set(tokenize("논문이"))


def test_mask_hides_secret_shapes_before_cutting():
    masker = Masker()
    pair = "to" + "ken" + "=" + "abcdef" + "123456"
    text = pair + " and sk-" + "a1" * 12 + " call 010-1234-5678"
    shown = masker.clip(text)
    assert "abcdef" not in shown
    assert "a1a1a1" not in shown
    assert "5678" not in shown


def test_profile_pattern_extends_the_mask():
    import re

    masker = Masker([re.compile(r"비밀번호\s*\S+")])
    assert masker.clip("비밀번호 hunter2 입니다") == "*** 입니다"


def test_secret_straddling_the_cut_is_still_masked():
    masker = Masker()
    text = "x" * 150 + " to" + "ken=" + "s" * 40
    assert "sss" not in masker.clip(text)
