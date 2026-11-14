# Test cases for .semgrep/rules/no-secrets-in-logs.yaml (#57), run with
#   uvx --from semgrep semgrep --test --config .semgrep/rules .semgrep/tests
# "ruleid" marks a line the rule must flag; "ok" one it must not.
# ruff: noqa
# pyright: basic
import logging

from character_planner.logs import redact

logger = logging.getLogger(__name__)


def tokens(token, settings, stored):
    # ruleid: no-secrets-in-logs
    logger.info("token %s", token.access_token)

    # ruleid: no-secrets-in-logs
    logging.warning(f"Bearer {stored.access_token}")

    secret = settings.bnet_client_secret.get_secret_value()
    # ruleid: no-secrets-in-logs
    logger.debug("client secret is %s", secret)

    # ruleid: no-secrets-in-logs
    print(token.access_token)

    header = {"Authorization": f"Bearer {token.access_token}"}
    # ruleid: no-secrets-in-logs
    logger.error("request headers: %s", header)

    # ruleid: no-secrets-in-logs
    raise ValueError(f"refused token {token.access_token}")


def facts_about_tokens(token, settings, stored):
    # ok: no-secrets-in-logs
    logger.info("New Battle.net app token, valid for %.0f hours", token.expires_at / 3600)

    # ok: no-secrets-in-logs
    logger.info("token present: %s", bool(token.access_token))

    # ok: no-secrets-in-logs
    logger.info("token length %d", len(stored.access_token))

    # ok: no-secrets-in-logs
    logger.info("redacted: %s", redact(f"Bearer {token.access_token}"))

    secret = settings.bnet_client_secret.get_secret_value()
    # Sent where it belongs: the token endpoint, not a log.
    # ok: no-secrets-in-logs
    send(auth=(settings.bnet_client_id, secret))

    # ok: no-secrets-in-logs
    raise ValueError("Battle.net refused the client ID and secret: check BNET_CLIENT_SECRET")


def send(auth):
    return auth
