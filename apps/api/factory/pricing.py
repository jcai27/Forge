"""What model usage costs, and when a provider failure says nothing about the agent.

A call to a named model with a known price is priced on its input and output tokens separately;
output includes the model's reasoning, and input the provider served from its prompt cache is billed
at the cached rate when one is configured. Anything else falls back to one flat rate per token.
Prices are configuration: check them against the provider before relying on a figure.
"""

import re

from factory.config import settings

DATED = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def model_name(agent):
    """The provider model a call went to, when it was named. Scripted and injected models have none."""
    model = getattr(agent, "model", None)
    return model if isinstance(model, str) else None


def prices(model):
    """(input, output, cached input) in dollars per token, or None when the model has no configured price."""
    if not model:
        return None
    table = settings().model_prices
    row = table.get(model) or table.get(DATED.sub("", model))
    if not row:
        return None
    return row[0] / 1_000_000, row[1] / 1_000_000, (row[2] if len(row) > 2 else row[0]) / 1_000_000


def cached_tokens(usage):
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    return min(max(0, cached), usage.input_tokens)


def usage_cost(usage, model=None):
    row = prices(model)
    if row is None:
        return usage.total_tokens * settings().estimated_token_cost
    cached = cached_tokens(usage)
    return (usage.input_tokens - cached) * row[0] + cached * row[2] + usage.output_tokens * row[1]


def reservation(model, input_bound, output_bound):
    """What to set aside before a call: an upper bound on the request and an allowance for the reply."""
    row = prices(model)
    if row is None:
        return (input_bound + output_bound) * settings().estimated_token_cost
    return input_bound * row[0] + output_bound * row[1]


def provider_unavailable(error):
    """Whether a failure means the provider could not be reached or would not serve the request.

    A dropped connection, a provider timeout, a rate limit and a provider-side error say nothing about
    the agent or the builder. The work is to be done again later, not scored or abandoned.
    """
    import openai

    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)):
            return True
        error = error.__cause__ or error.__context__
    return False


def reasoning(effort):
    """Model settings for a configured reasoning effort; nothing when none is configured."""
    if not effort:
        return None
    from openai.types.shared import Reasoning

    return Reasoning(effort=effort)
