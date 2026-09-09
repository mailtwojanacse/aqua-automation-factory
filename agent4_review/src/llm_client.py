"""LLM wrapper for Agent 4's review step. Four backends, selected via the
LLM_BACKEND env var:

- "anthropic_api" (default) - calls api.anthropic.com via the `anthropic`
  package. Needs ANTHROPIC_API_KEY.
- "openai_api" - calls the OpenAI API (ChatGPT) via the `openai` package.
  Needs OPENAI_API_KEY.
- "azure_openai" - calls an Azure OpenAI deployment via the `openai`
  package's AzureOpenAI client. Needs AZURE_OPENAI_API_KEY,
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT.
- "claude_cli" - shells out to the already-authenticated `claude` CLI in
  headless mode (`claude -p`), reusing whatever Claude subscription is
  logged in on this machine. No API key needed. Convenient for local
  dev/demoing, but not meant for unattended production volume - a
  subscription's usage limits aren't built for that.

All four are real deployment options. GitHub Copilot and Cursor are not -
they're IDE-embedded assistants with no general-purpose completion API a
script like this can call, so they can't be wired in the same way.

Transient failures (rate limits, momentary connection/timeout/5xx errors)
are retried with exponential backoff - see _with_retries. Auth and
bad-request errors are never retried; no amount of waiting fixes a bad key
or a malformed request, so failing fast there is more useful than a slow,
guaranteed-to-fail wait.
"""
import os
import subprocess
import time

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "anthropic_api")
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0


def generate(system_prompt, user_prompt, model=None, max_tokens=2000):
    if LLM_BACKEND == "claude_cli":
        return _generate_via_claude_cli(system_prompt, user_prompt, model)
    if LLM_BACKEND == "openai_api":
        return _generate_via_openai(system_prompt, user_prompt, model, max_tokens)
    if LLM_BACKEND == "azure_openai":
        return _generate_via_azure_openai(system_prompt, user_prompt, max_tokens)
    return _generate_via_anthropic_api(system_prompt, user_prompt, model, max_tokens)


def _with_retries(call, retryable_exceptions, max_attempts=MAX_RETRY_ATTEMPTS,
                   base_delay=RETRY_BASE_DELAY_SECONDS, sleep=None):
    """Call `call()`, retrying with exponential backoff (1s, 2s, 4s, ...) on
    any of `retryable_exceptions`. Anything else propagates immediately;
    once max_attempts is used up the last error propagates too - a
    transient hiccup deserves a retry, a permanent one doesn't deserve a
    slower failure."""
    # sleep=None (looked up here, at call time), not sleep=time.sleep as
    # the default - a default argument is evaluated once at import time, so
    # binding it directly to time.sleep would permanently capture the real
    # function and make it unpatchable in tests (monkeypatching time.sleep
    # afterward can't reach an already-bound default).
    sleep = sleep or time.sleep
    attempt = 0
    while True:
        try:
            return call()
        except retryable_exceptions:
            attempt += 1
            if attempt >= max_attempts:
                raise
            sleep(base_delay * (2 ** (attempt - 1)))


def _generate_via_anthropic_api(system_prompt, user_prompt, model, max_tokens):
    # Imported lazily so the module can be loaded (e.g. for --dry-run) on a VM
    # where the anthropic package isn't installed yet.
    from anthropic import Anthropic, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    def call():
        response = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_tokens,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    return _with_retries(call, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError))


def _chat_completion(client, model, system_prompt, user_prompt, max_tokens):
    """Shared request/response shape for OpenAI and Azure OpenAI - both use
    the same chat.completions API, just a different client and model value."""
    from openai import APIConnectionError, APITimeoutError, RateLimitError, InternalServerError

    def call():
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    return _with_retries(call, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError))


def _generate_via_openai(system_prompt, user_prompt, model, max_tokens):
    # Imported lazily, same reasoning as the anthropic import above.
    from openai import OpenAI

    client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _chat_completion(client, model or OPENAI_MODEL, system_prompt, user_prompt, max_tokens)


def _generate_via_azure_openai(system_prompt, user_prompt, max_tokens):
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )
    # Azure addresses models by deployment name, not the model family name.
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    return _chat_completion(client, deployment, system_prompt, user_prompt, max_tokens)


def _generate_via_claude_cli(system_prompt, user_prompt, model):
    cmd = [
        "claude", "-p", "--output-format", "text",
        "--system-prompt", system_prompt,
        "--tools", "",  # plain text completion only - no file/bash tool access
        "--no-session-persistence",
    ]
    if model or DEFAULT_MODEL:
        cmd += ["--model", model or DEFAULT_MODEL]
    cmd.append(user_prompt)

    def call():
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")
        return result.stdout.strip()

    # No structured exception types to tell a transient failure from a
    # permanent one apart from a bare CLI exit code, so retry any failure -
    # but only once (max_attempts=2), so a truly broken invocation (bad
    # model name, not logged in) doesn't pay the same retry cost as a real
    # network blip.
    return _with_retries(call, (RuntimeError,), max_attempts=2)
