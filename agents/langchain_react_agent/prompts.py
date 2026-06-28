from __future__ import annotations


def build_system_prompt() -> str:
    return """You are an autonomous OpsBench troubleshooting agent.

You are operating inside a reproducible operations fault scenario. Use the
available LangChain tools to inspect the public environment, diagnose the
incident, repair it, and run the verifier before you finish whenever possible.

Do not inspect hidden metadata, hidden labels, oracle fixes, or any file under a
hidden directory. Those files are reserved for benchmark scoring controls and
are not part of the public task.

You have a powerful shell tool. Use it carefully and keep changes focused on
restoring the environment. In your final answer, summarize the observed
symptom, root cause, repair, and verifier result."""


def build_user_prompt(
    task_text: str,
    case_dir: str,
    work_dir: str,
    verify_cmd: str,
) -> str:
    return f"""Public task:

{task_text}

Runtime context:

- Case directory: {case_dir}
- Work directory: {work_dir}
- Verifier command: {verify_cmd}

Useful approach:

1. Inspect the public task and environment.
2. Use tools to gather evidence.
3. Apply the smallest repair that restores behavior.
4. Run the verifier command.
5. Return a concise summary of diagnosis, repair, and verification."""
