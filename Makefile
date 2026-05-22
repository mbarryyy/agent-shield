# Agent Shield — developer entrypoints.
.DEFAULT_GOAL := help
.PHONY: help preflight doctor test integration integration-auth smoke eval eval-real air-gap-verify lint typecheck

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n",$$1,$$2}'

preflight: ## Full environment GO/NO-GO check without printing secrets
	@scripts/preflight.sh

doctor: ## Preflight: toolchain + infra reachability
	@scripts/preflight.sh

lint: ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## mypy our code
	uv run mypy packages

test: ## Unit + contract tests with coverage gate
	uv run pytest packages contracts tests/test_preflight.py \
	  --cov=packages --cov-report=term-missing --cov-fail-under=80

integration: ## docker-compose smoke + mocked AgentDojo A/B (no secrets)
	docker compose -f infra/docker-compose.yml up -d postgres redis minio chromadb
	uv run python infra/wait_for_health.py
	uv run pytest tests/integration -m integration

integration-auth: ## Enterprise-auth integration (mailhog + ephemeral secrets, ADR-0013)
	docker compose -f infra/docker-compose.yml up -d postgres redis minio chromadb mailhog
	SHIELD_AUTH_MODE=enterprise uv run python infra/wait_for_health.py
	SHIELD_AUTH_MODE=enterprise \
	  SHIELD_SESSION_SECRETS="local:$$(uv run python infra/secrets/gen.py session)" \
	  SHIELD_PASSWORD_PEPPERS="local:$$(uv run python infra/secrets/gen.py pepper)" \
	  SHIELD_AUTH_FERNET_KEYS="local:$$(uv run python infra/secrets/gen.py fernet)" \
	  uv run pytest tests/integration/auth -m integration_auth

smoke: ## Quick mocked AgentDojo user_task_0 smoke
	SHIELD_LLM_BACKEND=mock uv run python -m shield_eval.run_ab \
	  --suite banking --user-task user_task_0 --smoke

eval: ## Full mocked metrics table (ASR/UR/DR/FPR/IL/TO)
	SHIELD_LLM_BACKEND=mock uv run python -m shield_eval.run_ab --full \
	  --suite banking --attack important_instructions --metrics asr,ur,dr,fpr,il,to

eval-real: ## Budget-estimated real-provider slice; API call intentionally skipped
	ANTHROPIC_API_KEY= SHIELD_LLM_BACKEND=real uv run python -m shield_eval.run_ab --full \
	  --suite banking --attack important_instructions --backend real \
	  --model claude-haiku-4-5-20251001 --arms A0,A2 \
	  --user-task user_task_2 --injection-task injection_task_6 \
	  --samples 1 --serialized-prompt-chars 3000 --max-output-tokens 2000

air-gap-verify: ## #7 moat: assert zero-egress under the local-serving profile
	uv run python -m shield_governance.air_gap_verify
