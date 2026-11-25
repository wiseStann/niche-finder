"""The title rule of ru_zakupki: a procurement counts as having the phrase in its title only when every significant word of the
phrase is there (until 2026-11-25 one word was enough, and the hotel phrase counted boiler rooms and radio contracts)."""
from __future__ import annotations

from nichefinder.stages.ru_zakupki import in_title, title_rule


def _has(phrase: str, title: str) -> bool:
    return in_title(title_rule(phrase), title)


def test_every_word_of_the_phrase_must_be_in_the_title():
    assert _has("система управления отелем", "Внедрение автоматизированной системы управления отелем")
    assert _has("система управления отелем", "Поставка системы управления отеля «Волна»")          # another case ending
    assert not _has("система управления отелем", "Техническое обслуживание системы управления котельной")
    assert not _has("гостиница программа бронирования", "Оказание услуг по организации проживания и культурной программы")


def test_a_stem_must_start_a_word_and_a_short_word_must_stand_whole():
    assert not _has("система управления отелем", "Система управления «Аристотель»")             # the letters, not the word
    assert _has("tms система", "Внедрение системы TMS для перевозок")
    assert not _has("tms система", "Обслуживание системы ATMS")
    assert _has("1с:бухгалтерия", "Сопровождение программы 1С:Бухгалтерия 8")


def test_prepositions_are_skipped_and_yo_is_e():
    assert _has("программа для бухгалтерского учета", "Программа бухгалтерского учёта для МУП")
    assert title_rule("и в на") == [] and not _has("и в на", "Поставка мебели")              # no significant word, no match
