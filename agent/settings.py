import os


class AgentSettings:
    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")

        self.planner_model = os.getenv("PLANNER_MODEL", "gpt-4o")
        self.extraction_model = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")
        self.fallback_model = os.getenv("FALLBACK_MODEL", "claude-3-5-sonnet")

        self.search_provider = os.getenv("SEARCH_PROVIDER", "duckduckgo").lower()
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.serpapi_api_key = os.getenv("SERPAPI_API_KEY")
        self.serpapi_engine = os.getenv("SERPAPI_ENGINE", "google")

        self.max_urls = int(os.getenv("AGENT_MAX_URLS", "12"))
        self.search_results_per_query = int(os.getenv("AGENT_SEARCH_RESULTS_PER_QUERY", "5"))
        self.scrape_concurrency = int(os.getenv("AGENT_SCRAPE_CONCURRENCY", "4"))
        self.scrape_timeout_sec = int(os.getenv("AGENT_SCRAPE_TIMEOUT_SEC", "30"))
        self.scrape_retries = int(os.getenv("AGENT_SCRAPE_RETRIES", "2"))
        self.scrape_delay_sec = float(os.getenv("AGENT_SCRAPE_DELAY_SEC", "0.2"))

        self.credit_cost_search = int(os.getenv("CREDIT_COST_SEARCH", "5"))
        self.credit_cost_scrape = int(os.getenv("CREDIT_COST_SCRAPE", "10"))
        self.credit_cost_planner = int(os.getenv("CREDIT_COST_LLM_PLANNER", "30"))
        self.credit_cost_extraction = int(os.getenv("CREDIT_COST_LLM_EXTRACTION", "20"))
        self.credit_cost_fallback = int(os.getenv("CREDIT_COST_LLM_FALLBACK", "40"))

        self.plan_max_steps = int(os.getenv("AGENT_PLAN_MAX_STEPS", "6"))
        self.schema_max_retries = int(os.getenv("AGENT_SCHEMA_MAX_RETRIES", "2"))
        self.result_ttl_hours = int(os.getenv("AGENT_RESULT_TTL_HOURS", "24"))

        self.default_max_credits = int(os.getenv("AGENT_DEFAULT_MAX_CREDITS", "2500"))

    def validate(self) -> None:
        if self.planner_model == self.extraction_model:
            raise ValueError(
                "PLANNER_MODEL and EXTRACTION_MODEL must be different to enforce multi-model architecture."
            )
        if self.llm_provider not in {"openai", "anthropic"}:
            raise ValueError("LLM_PROVIDER must be 'openai' or 'anthropic'.")
