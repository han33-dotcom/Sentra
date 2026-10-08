from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    authorization_url: str
    token_url: str
    scopes: tuple[str, ...]
    sample_url: str
    records_key: str


PROVIDERS = {
    "google_health": Provider(
        "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
        tuple("https://www.googleapis.com/auth/googlehealth." + scope + ".readonly"
              for scope in ("activity_and_fitness", "sleep", "health_metrics_and_measurements")),
        "https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints", "dataPoints"),
    "whoop": Provider(
        "https://api.prod.whoop.com/oauth/oauth2/auth", "https://api.prod.whoop.com/oauth/oauth2/token",
        ("read:cycles", "read:recovery", "read:sleep", "read:workout", "offline"),
        "https://api.prod.whoop.com/developer/v2/cycle", "records"),
}
