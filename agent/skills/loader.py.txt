"""Load a skill.md: YAML front matter -> strictly validated SkillMeta.
Unknown keys are rejected so a typo in a rule cannot be silently ignored.
The Markdown body is documentation for humans and is not executed."""
from __future__ import annotations
import hashlib, pathlib, re
from typing import Any, Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TriggerSignature(_S):
    pattern: str
    source: str
    signal: Literal["denial", "multi_pdb"] = "denial"


class RequiredEvidence(_S):
    dataset: str
    kinds: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    max_age_seconds: int


class Rule(_S):
    id: str
    when: dict[str, list[list[Any]]]
    then: dict[str, Any]
    why: str


class SkillMeta(_S):
    skill_id: str
    skill_version: str
    title: str
    status: Literal["draft", "candidate", "active", "deprecated"]
    owner: str
    lifecycle_stages: list[str]
    trigger_signatures: list[TriggerSignature]
    supported_environments: dict[str, Any]
    required_evidence: list[RequiredEvidence]
    freshness_limits_seconds: dict[str, int]
    decision_tree_version: str
    prohibited_actions: list[str]
    remediation_catalog_refs: list[str]
    evaluation_fixtures: dict[str, str]
    declared_facts: list[str]
    rules: list[Rule]


FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


def load(path: str | pathlib.Path) -> tuple[SkillMeta, str, str]:
    raw = pathlib.Path(path).read_bytes()
    m = FRONT.match(raw.decode("utf-8"))
    if not m:
        raise ValueError(f"{path}: missing YAML front matter")
    meta = SkillMeta.model_validate(yaml.safe_load(m.group(1)))
    return meta, m.group(2), hashlib.sha256(raw).hexdigest()
