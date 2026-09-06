with open("src/enterprise_ekb/a2a_runtime.py", "r") as f:
    content = f.read()

sub_agent_handler = """    def delegate_sub_task_handler(payload: dict[str, Any]) -> None:
        _ = payload.get("target_agent")
        _ = payload.get("payload", {})
        _ = payload.get("metadata", {}).get("supervisor_id")

    dispatcher.register("delegate_sub_task", delegate_sub_task_handler)
"""

if "delegate_sub_task_handler" not in content:
    content = content.replace("    dispatcher.register(\"evaluate_skill\", evaluate_skill_handler)", "    dispatcher.register(\"evaluate_skill\", evaluate_skill_handler)\n" + sub_agent_handler)
    with open("src/enterprise_ekb/a2a_runtime.py", "w") as f:
        f.write(content)
