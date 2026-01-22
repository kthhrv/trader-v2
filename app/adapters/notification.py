import httpx
from app.core.config import settings


class HomeAssistantNotifier:
    """
    Async notifier for Home Assistant using httpx.
    """

    def __init__(self):
        self.api_url = settings.HA_API_URL
        self.token = settings.HA_ACCESS_TOKEN
        self.notify_entity = settings.HA_NOTIFY_ENTITY

    async def send_notification(
        self, title: str, message: str, priority: str = "normal"
    ):
        """
        Sends a notification to HA.
        """
        if not self.token:
            return

        headers = {
            "Authorization": f"Bearer {self.token.get_secret_value()}",
            "Content-Type": "application/json",
        }

        domain = "notify"
        service = self.notify_entity.replace("notify.", "")
        url = f"{self.api_url.rstrip('/')}/api/services/{domain}/{service}"

        data = {
            "title": title,
            "message": message,
        }

        if priority == "high":
            data["data"] = {
                "ttl": 0,
                "priority": "high",
                "channel": "alarm",
                "push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}},
            }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers=headers, json=data, timeout=5.0
                )
                response.raise_for_status()
        except Exception as e:
            # Don't use logger.error here to avoid recursion loops if attached to logger
            print(f"Failed to send HA notification: {e}")
