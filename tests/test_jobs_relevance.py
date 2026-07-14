from __future__ import annotations

from pathlib import Path

import pytest

from edgefinder.jobs.relevance import JobProfile, classify_seniority, load_profile, score_job

PROFILE = JobProfile(
    skills_have=["python", "sql", "excel", "power bi"],
    skills_learning=["dbt", "azure"],
    target_roles=["data engineer", "analyst", "business intelligence", "konsulent"],
    locations={"Trondheim": 1.0, "Oslo": 0.8, "remote": 0.9},
    default_location_weight=0.5,
    seniority={"internship": 1.0, "graduate": 1.0, "junior": 0.9, "senior": 0.3},
    unspecified_seniority_weight=0.7,
)


def test_missing_profile_scores_everything_fifty() -> None:
    score, breakdown = score_job("Senior Data Engineer", "Python og SQL.", "Oslo", None)
    assert score == 50.0
    assert breakdown == {}


def test_load_profile_returns_none_for_missing_and_raises_on_malformed(tmp_path: Path) -> None:
    assert load_profile(tmp_path / "absent.yaml") is None
    broken = tmp_path / "broken.yaml"
    broken.write_text("skills_have: {not: [valid")
    with pytest.raises(ValueError):
        load_profile(broken)
    wrong_field = tmp_path / "wrong.yaml"
    wrong_field.write_text("seniority: yes\n")
    with pytest.raises(ValueError):
        load_profile(wrong_field)


def test_load_profile_reads_the_example_file() -> None:
    profile = load_profile(Path("profile.example.yaml"))
    assert profile is not None
    assert profile.target_roles


def test_seniority_classifier_buckets() -> None:
    assert classify_seniority("Sommerjobb 2027 – analyse") == "internship"
    assert classify_seniority("Graduate program for nyutdannede") == "graduate"
    assert classify_seniority("Junior utvikler") == "junior"
    assert classify_seniority("Senior Data Engineer") == "senior"
    assert classify_seniority("Leder for økonomiavdelingen") == "senior"
    assert classify_seniority("Data Engineer") == "unspecified"
    assert classify_seniority("Prosjektleder bygg") == "unspecified"  # 'leder' inside a word is not a bucket hit


def test_relevant_graduate_job_outscores_irrelevant_senior_job() -> None:
    graduate, graduate_parts = score_job(
        "Data Engineer – nyutdannet",
        "Vi søker nyutdannet data engineer med Python og SQL i Trondheim.",
        "Trondheim",
        PROFILE,
    )
    senior, _ = score_job(
        "Senior sykepleier",
        "Sykepleier med lang erfaring søkes til hjemmetjenesten.",
        "Bodø",
        PROFILE,
    )
    assert graduate > 80
    assert senior < 40
    assert set(graduate_parts) == {"role_match", "skills", "location", "seniority"}
    assert sum(graduate_parts.values()) == pytest.approx(graduate, abs=0.2)


def test_title_role_match_beats_excerpt_only_match() -> None:
    in_title, _ = score_job("Business Intelligence Consultant", "Rapportering.", "Oslo", PROFILE)
    in_excerpt, _ = score_job("Rapporteringsansvarlig", "Du blir vår nye business intelligence-ressurs.", "Oslo", PROFILE)
    assert in_title > in_excerpt


def test_remote_weight_applies_when_ad_signals_remote() -> None:
    remote, _ = score_job("Analyst", "Fully remote analyst role. Python.", "Ukjent", PROFILE)
    unknown, _ = score_job("Analyst", "Analyst role. Python.", "Ukjent", PROFILE)
    assert remote > unknown
