# Use Backblaze B2 native HTTP API instead of an SDK

We chose to upload Backups to Backblaze B2 by calling the B2 native JSON API directly with `httpx`, rather than pulling in `b2sdk` or `boto3`. The upload flow is small (authorize account, get upload URL, POST the file), and avoiding a heavy SDK keeps the Docker image and dependency surface small. The trade-off is that we own a thin wrapper for B2's API.
