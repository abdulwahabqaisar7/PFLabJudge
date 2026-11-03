"""Verdicts supported by the CPJudge engine."""
from enum import Enum


class Verdict(str, Enum):
    AC = "AC"   # Accepted
    WA = "WA"   # Wrong Answer
    TLE = "TLE" # Time Limit Exceeded
    MLE = "MLE" # Memory Limit Exceeded
    RE = "RE"   # Runtime Error
    CE = "CE"   # Compilation Error
    OLE = "OLE" # Output Limit Exceeded

    def is_accepted(self) -> bool:
        return self == Verdict.AC

    @property
    def description(self) -> str:
        descriptions = {
            Verdict.AC: "Accepted",
            Verdict.WA: "Wrong Answer",
            Verdict.TLE: "Time Limit Exceeded",
            Verdict.MLE: "Memory Limit Exceeded",
            Verdict.RE: "Runtime Error",
            Verdict.CE: "Compilation Error",
            Verdict.OLE: "Output Limit Exceeded",
        }
        return descriptions.get(self, "Unknown Verdict")
