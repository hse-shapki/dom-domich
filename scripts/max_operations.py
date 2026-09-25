"""Явные операционные команды MAX; токен и webhook secret читаются только из окружения."""

import argparse
import asyncio
import os

import httpx

from dom_domych.infrastructure.max.client import MAX_API_BASE_URL, MaxApiClient


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


async def run(arguments: argparse.Namespace) -> None:
    token = _required("MAX_BOT_TOKEN")
    timeout = httpx.Timeout(connect=5, read=30, write=30, pool=5)
    async with httpx.AsyncClient(base_url=MAX_API_BASE_URL, timeout=timeout) as http:
        client = MaxApiClient(http, token)
        if arguments.command == "probe":
            identity = await client.get_me()
            print(f"bot_user_id={identity.user_id} username={identity.username or '-'}")
        elif arguments.command == "subscriptions":
            subscriptions = await client.list_webhooks()
            print(f"subscription_count={len(subscriptions)}")
            for subscription in subscriptions:
                print(f"url={subscription.get('url', '<missing>')}")
        elif arguments.command == "register":
            await client.register_webhook(
                arguments.url,
                _required("MAX_WEBHOOK_SECRET"),
                tuple(arguments.update_type),
            )
            print("webhook_registered=true")
        else:
            await client.delete_webhook(arguments.url)
            print("webhook_deleted=true")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("probe")
    subparsers.add_parser("subscriptions")
    register = subparsers.add_parser("register")
    register.add_argument("--url", required=True)
    register.add_argument("--update-type", action="append", required=True)
    delete = subparsers.add_parser("delete")
    delete.add_argument("--url", required=True)
    arguments = parser.parse_args()
    asyncio.run(run(arguments))


if __name__ == "__main__":
    main()
