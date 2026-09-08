from .config import settings
from .filesystem import read_json_safe


def _load() -> dict:
    data = read_json_safe(settings.agents_config, {"agents": {}})
    return data.get("agents", {})


def list_agents() -> list[dict]:
    agents = _load()
    return [
        {"id": k, **v, "name": v.get("name", k), "command": v.get("command", k)}
        for k, v in agents.items()
    ]


def get_agent_command(agent_id: str) -> str:
    agents = _load()
    if agent_id not in agents:
        raise ValueError(f"Unknown agent: {agent_id}")
    cfg = agents[agent_id]
    cmd = cfg["command"]
    model = cfg.get("model", "").strip()
    if model and "--model" not in cmd and cmd.lstrip().startswith("claude"):
        cmd = f"{cmd} --model {model}"
    return cmd


def validate_agent(agent_id: str) -> bool:
    return agent_id in _load()
