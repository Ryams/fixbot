class FixbotError(Exception):
    """Base exception for all fixbot errors."""


class ConfigError(FixbotError):
    """Invalid or missing configuration."""


class ConfigMissingKeyError(ConfigError):
    """A required config key is missing."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Missing required config key: {key}")


class ConfigEnvVarError(ConfigError):
    """A referenced environment variable is not set."""

    def __init__(self, var_name: str, config_path: str):
        self.var_name = var_name
        self.config_path = config_path
        super().__init__(
            f"Environment variable ${{{var_name}}} referenced in "
            f"config key '{config_path}' is not set"
        )


class MCPServerError(FixbotError):
    """An MCP server failed to start or respond."""


class AgentError(FixbotError):
    """The Claude agent returned an error or exceeded limits."""


class AgentBudgetExceeded(AgentError):
    """Agent hit max_budget_usd limit."""
