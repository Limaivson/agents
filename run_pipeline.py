import sys
from pathlib import Path
from typing import TypedDict, List
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END

llm = ChatOllama(
    model="qwen2.5-coder:7b",
    temperature=0.2,
    num_ctx=8192
)


class GeneralAuditorEvaluation(BaseModel):
    approved: bool = Field(description="True if the code meets 100% of the requirements without grave pending issues.")
    consolidated_opinion: str = Field(description="Summary of reasons for approval or list of pending issues requiring refactoring")


class PipelineState(TypedDict):
    file_name: str
    project_context: str
    actual_code: str
    analysis: str
    tests: str
    expert_reviews: List[str]
    final_audit: str
    approved: bool
    iteration: int
    max_iterations: int


def load_prompt(file_name: str) -> str:
    path = Path("prompts") / file_name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "You are a senior software engineer."


# --- AGENT NODES ---
def analyst_agent(state: PipelineState):
    iteration = state.get("iteration", 0) + 1
    print(f"\n🚀 [Cycle {iteration}/{state['max_iterations']}] 1. Global Analyst inspecting code...")
    system_prompt = load_prompt("1_analyst.md")
    
    instruction = f"Context:\n{state['project_context']}\n\nCurrent Code:\n{state['actual_code']}"
    if state.get("final_audit") and not state.get("approved"):
        instruction += f"\n\nTHE AUDITOR REJECTED THE PREVIOUS VERSION:\n{state['final_audit']}\nFocus the analysis on resolving these critical issues."
        
    response = llm.invoke([("system", system_prompt), ("user", instruction)])
    return {"analysis": response.content, "iteration": iteration, "expert_reviews": []}


def tester_agent(state: PipelineState):
    print("🧪 2. Test Engineer designing validation suite and edge cases...")
    response = llm.invoke([
        ("system", load_prompt("2_tester.md")),
        ("user", f"Code:\n{state['actual_code']}\n\nArchitecture Analysis:\n{state['analysis']}")
    ])
    return {"tests": response.content}


def refactor_agent(state: PipelineState):
    print("🛠️  3. Implementer Engineer applying code fixes...")
    instruction = f"""
    Original Code:
    {state['actual_code']}
    
    Analyst Guidelines:
    {state['analysis']}
    
    Test Suite / Requirements:
    {state['tests']}
    
    Return the complete, updated, and functional code file.
    """
    response = llm.invoke([("system", load_prompt("3_refactor.md")), ("user", instruction)])
    return {"actual_code": response.content}


def perf_reviewer(state: PipelineState):
    print("⚡ 4. Performance Specialist Reviewer auditing...")
    response = llm.invoke([("system", load_prompt("4_review_perf.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[PERFORMANCE]: {response.content}"]}


def io_reviewer(state: PipelineState):
    print("🛡️  5. Timeouts and I/O Reviewer auditing...")
    response = llm.invoke([("system", load_prompt("5_review_errors.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[ERRORS/IO]: {response.content}"]}


def clean_reviewer(state: PipelineState):
    print("✨ 6. Clean Code and Typing Reviewer auditing...")
    response = llm.invoke([("system", load_prompt("6_review_clean.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[CLEAN CODE]: {response.content}"]}


def safety_reviewer(state: PipelineState):
    print("🔒 7. Resource Safety Reviewer auditing...")
    response = llm.invoke([("system", load_prompt("7_review_safety.md")), ("user", state["actual_code"])])
    return {"expert_reviews": state["expert_reviews"] + [f"[SECURITY]: {response.content}"]}


def general_auditor_agent(state: PipelineState):
    print("⚖️  8. General Auditor consolidating committee feedback...")
    reviews = "\n\n".join(state["expert_reviews"])
    instruction = f"""
    Current Code:
    {state['actual_code']}
    
    Opinions from the 4 Specialists:
    {reviews}
    
    Evaluate whether the code is production-ready without severe pending issues.
    """
    auditor_llm = llm.with_structured_output(GeneralAuditorEvaluation)
    evaluation = auditor_llm.invoke([("system", load_prompt("8_general_audit.md")), ("user", instruction)])
    return {"approved": evaluation.approved, "final_audit": evaluation.consolidated_opinion}


def evaluate_condition(state: PipelineState):
    if state["approved"]:
        print(f"\n🎉 [SUCCESS]: Code approved by the General Auditor in iteration {state['iteration']}!")
        return END
    if state["iteration"] >= state["max_iterations"]:
        print(f"\n⚠️  [WARNING]: Limit of {state['max_iterations']} iterations reached. Delivering the latest version.")
        return END
    print(f"\n🔄 [FEEDBACK LOOP]: Auditor rejected the code. Reason:\n{state['final_audit']}")
    return "analyst"


# 3. LangGraph Setup
builder = StateGraph(PipelineState)
builder.add_node("analyst", analyst_agent)
builder.add_node("tests", tester_agent)
builder.add_node("refactorer", refactor_agent)
builder.add_node("rev_perf", perf_reviewer)
builder.add_node("rev_io", io_reviewer)
builder.add_node("rev_clean", clean_reviewer)
builder.add_node("rev_safety", safety_reviewer)
builder.add_node("general_auditor", general_auditor_agent)

builder.set_entry_point("analyst")
builder.add_edge("analyst", "tests")
builder.add_edge("tests", "refactorer")
builder.add_edge("refactorer", "rev_perf")
builder.add_edge("rev_perf", "rev_io")
builder.add_edge("rev_io", "rev_clean")
builder.add_edge("rev_clean", "rev_safety")
builder.add_edge("rev_safety", "general_auditor")

builder.add_conditional_edges("general_auditor", evaluate_condition, {
    "analyst": "analyst",
    END: END
})

pipeline = builder.compile()

# --- TERMINAL EXECUTION ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_pipeline.py <file_path> [optional_context]")
        print("Example: python run_pipeline.py aruco_follower.py 'Robotics navigation control'")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")
    context = sys.argv[2] if len(sys.argv) > 2 else "Critical engineering module."

    print(f"Starting 8-agent pipeline for: {file_path.name} ({len(content)} characters)")

    payload = {
        "file_name": file_path.name,
        "project_context": context,
        "actual_code": content,
        "analysis": "",
        "tests": "",
        "expert_reviews": [],
        "final_audit": "",
        "approved": False,
        "iteration": 0,
        "max_iterations": 3
    }

    result = pipeline.invoke(payload)

    # Save optimized version to a new file (e.g., aruco_follower_perfect.py)
    output_file = file_path.parent / f"{file_path.stem}_perfect{file_path.suffix}"
    output_file.write_text(result["actual_code"], encoding="utf-8")

    # Save test suite generated by Agent 2
    tests_file = file_path.parent / f"test_{file_path.stem}.py"
    tests_file.write_text(result["tests"], encoding="utf-8")

    print(f"\n Successfully completed!")
    print(f" Optimized code saved to: {output_file.name}")
    print(f" Test suite saved to: {tests_file.name}")