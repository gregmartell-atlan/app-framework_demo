"""Local development entrypoint for the GitHub connector.

Run this script to start the app in combined handler+worker mode for local testing.

Usage:
    uv run python -m app.run_dev
"""

from application_sdk.dev import run_dev_combined

from app.connector import GitHubConnector


if __name__ == "__main__":
    run_dev_combined(GitHubConnector)
