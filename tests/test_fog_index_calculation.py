# Validation tests for the fog index calculation.
import pytest
from src.services.fog_index import fog_index, syllable_count, words, sentences


# 1. Syllable counting
class TestSyllableCount:

    # 1 syllable
    def test_monosyllabic(self):
        for word in ["cats", "run", "fast", "dogs", "jump", "fly", "low"]:
            assert syllable_count(word) == 1, f"'{word}' should have 1 syllable"

    # 2 syllables
    def test_bisyllabic(self):
        assert syllable_count("simple")  == 2
        assert syllable_count("Python")  == 2
        assert syllable_count("module")  == 2
        assert syllable_count("entry")   == 2
        assert syllable_count("project") == 2

    # 3+ syllables
    def test_polysyllabic(self):
        assert syllable_count("arithmetic")    == 4
        assert syllable_count("calculator")    == 4
        assert syllable_count("sophisticated") == 5

    def test_empty_word_returns_zero(self):
        assert syllable_count("") == 0

    def test_minimum_one_syllable_for_any_word(self):
        assert syllable_count("x") >= 1


# Word and sentence tokenisation
class TestTokenisation:

    def test_word_count_simple(self):
        assert len(words("Cats run fast.")) == 3

    def test_word_count_ignores_punctuation(self):
        assert len(words("Hello, world!")) == 2

    def test_contraction_counts_as_one_word(self):
        assert len(words("I don't have a cat.")) == 5

    def test_comment_mode_one_line_equals_one_sentence(self):
        assert len(sentences("Cats run fast.", kind="comment")) == 1

    def test_comment_mode_two_lines_equal_two_sentences(self):
        assert len(sentences("Cats run fast.\nDogs jump high.", kind="comment")) == 2

    def test_comment_mode_blank_lines_not_counted(self):
        assert len(sentences("Line one.\n\nLine two.", kind="comment")) == 2

    def test_doc_mode_splits_on_punctuation(self):
        assert len(sentences("First. Second.", kind="doc")) == 2


# These cases are chosen so every number can be confirmed by hand
class TestFogIndexFormula:

    def test_all_monosyllabic_one_sentence(self):
        # "Cats run fast."
        # words=3, sentences=1, syllables=3
        # score = 0.39*(3/1) + 11.8*(3/3) - 15.59 = 1.17 + 11.8 - 15.59 = -2.62
        score = fog_index("Cats run fast.", kind="comment")
        assert score == pytest.approx(-2.62, abs=0.01)

    def test_all_monosyllabic_two_sentences(self):
        # "Dogs jump high.\nBirds fly low."
        # words=6, sentences=2, syllables=6
        # score = 0.39*(6/2) + 11.8*(6/6) - 15.59 = 1.17 + 11.8 - 15.59 = -2.62
        # Same score as above: doubling words and sentences equally keeps ratios identical.
        score = fog_index("Dogs jump high.\nBirds fly low.", kind="comment")
        assert score == pytest.approx(-2.62, abs=0.01)

    def test_polysyllabic_words_raise_score(self):
        # "Sophisticated architecture."
        # words=2, sentences=1, syllables=9 (5+4)
        # score = 0.39*(2/1) + 11.8*(9/2) - 15.59 = 0.78 + 53.1 - 15.59 = 38.29
        score = fog_index("Sophisticated architecture.", kind="comment")
        assert score == pytest.approx(38.29, abs=0.01)

    def test_existing_regression_doc_mode(self):
        # "I don't have a cat. I have a dog."
        # words=9, sentences=2, syllables=9
        # score = 0.39*(9/2) + 11.8*(9/9) - 15.59 = -2.035
        score = fog_index("I don't have a cat. I have a dog.")
        assert score == pytest.approx(-2.035, abs=0.01)

    def test_more_sentences_lowers_score(self):
        # Splitting text into more sentences lowers words/sentences ratio gives a lower score.
        one_sentence = fog_index("Cats run fast and dogs jump high.", kind="comment")
        two_sentences = fog_index("Cats run fast.\nDogs jump high.", kind="comment")
        assert two_sentences < one_sentence

    def test_more_syllables_raises_score(self):
        # Same word count and sentence count. More syllables gives a higher score.
        simple  = fog_index("Cats run fast.", kind="comment")   # 3 syllables
        complex_ = fog_index("Sophisticated architecture.", kind="comment")  # 9 syllables
        assert complex_ > simple

    def test_empty_returns_none(self):
        assert fog_index("") is None

    def test_whitespace_only_returns_none(self):
        assert fog_index("   \n\n") is None