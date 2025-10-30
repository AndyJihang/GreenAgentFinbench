from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class RubricItem(BaseModel):
    id: str
    desc: str
    weight: float = 0.25

class Constraints(BaseModel):
    allowed_tools: List[str] = Field(default_factory=list)
    max_steps: int = 50
    time_budget_sec: int = 600

class EvidencePolicy(BaseModel):
    allowed_domains: Optional[List[str]] = None
    must_cite: bool = True

class AnswerContract(BaseModel):
    final_prefix: str = "FINAL ANSWER:"
    require_sources_dict: bool = True

class FinanceResearchTask(BaseModel):
    task_id: str
    category: str
    question: str
    constraints: Constraints = Field(default_factory=Constraints)
    evidence_policy: EvidencePolicy = Field(default_factory=EvidencePolicy)
    answer_contract: AnswerContract = Field(default_factory=AnswerContract)
    rubrics: List[RubricItem] = Field(default_factory=list)
    context_urls: Optional[List[str]] = None
    expected: Optional[Dict[str, Any]] = None

class SourceItem(BaseModel):
    url: str
    name: Optional[str] = None

class ToolStats(BaseModel):
    calls: Dict[str, int] = Field(default_factory=dict)

class AnswerSchema(BaseModel):
    final_answer: str
    sources: List[SourceItem] = Field(default_factory=list)
    work_notes: Optional[str] = None
    tool_trace: Optional[List[Dict[str, Any]]] = None
    tool_stats: Optional[ToolStats] = None

class PerTaskResult(BaseModel):
    task_id: str
    category: str
    success: bool
    score: float
    details: Dict[str, Any] = Field(default_factory=dict)
    answer: AnswerSchema

class AssessmentResult(BaseModel):
    purple_agent_url: str
    per_task: List[PerTaskResult]
    summary: Dict[str, Any]
