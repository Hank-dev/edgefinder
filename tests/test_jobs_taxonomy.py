from __future__ import annotations

from edgefinder.jobs.taxonomy import CLUSTERS, TAXONOMY, extract_skills


def test_clusters_are_the_six_from_the_spec() -> None:
    assert CLUSTERS == ["Programming", "Data & ML", "Cloud & Infra", "Finance & Econ", "Business & Methods", "Languages"]
    assert set(TAXONOMY) == set(CLUSTERS)


def test_synonyms_merge_into_one_canonical_skill() -> None:
    english = extract_skills("We need machine learning experience")
    norwegian = extract_skills("Erfaring med maskinlæring er et krav")
    abbreviated = extract_skills("Strong ML fundamentals required")
    assert ("Data & ML", "Machine Learning") in english
    assert english & norwegian & abbreviated == {("Data & ML", "Machine Learning")}


def test_word_boundaries_prevent_substring_hits() -> None:
    assert ("Programming", "Go") not in extract_skills("category management role")
    assert ("Programming", "Go") in extract_skills("Backend i Go og Python")
    assert ("Data & ML", "Machine Learning") not in extract_skills("html templates")  # 'ml' inside a word
    assert ("Programming", "C++") in extract_skills("Systems work in C++ daily")
    assert ("Programming", "C#") in extract_skills("Utvikling i C# og .NET")


def test_norwegian_characters_do_not_break_boundaries() -> None:
    assert ("Finance & Econ", "Regnskap") in extract_skills("Ansvar for regnskap og lønn")
    assert ("Finance & Econ", "Økonomistyring") in extract_skills("Erfaring med økonomistyring")


def test_each_skill_counted_once_per_text() -> None:
    found = extract_skills("Excel, excel og mer Excel med Power BI")
    assert ("Finance & Econ", "Excel") in found
    assert len([skill for _c, skill in found if skill == "Excel"]) == 1
