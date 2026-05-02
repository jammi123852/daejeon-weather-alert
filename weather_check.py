import os
import sys
from datetime import datetime
from typing import Any

import requests


DAEJEON_LATITUDE = 36.3504
DAEJEON_LONGITUDE = 127.3845

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def send_slack_message(message: str) -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL is missing.")

    payload = {
        "text": message,
    }

    response = requests.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()


def fetch_daejeon_weather() -> dict[str, Any]:
    params = {
        "latitude": DAEJEON_LATITUDE,
        "longitude": DAEJEON_LONGITUDE,
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "rain_sum",
            "snowfall_sum",
            "wind_speed_10m_max",
        ],
        "timezone": "Asia/Seoul",
        "forecast_days": 1,
    }

    response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
    response.raise_for_status()

    return response.json()


def judge_special_weather(weather_data: dict[str, Any]) -> list[str]:
    daily = weather_data.get("daily")

    if not daily:
        raise RuntimeError("Weather response does not contain daily data.")

    date = daily["time"][0]
    weather_code = daily["weather_code"][0]
    temp_max = daily["temperature_2m_max"][0]
    temp_min = daily["temperature_2m_min"][0]
    precipitation = daily["precipitation_sum"][0]
    rain = daily["rain_sum"][0]
    snowfall = daily["snowfall_sum"][0]
    wind_max = daily["wind_speed_10m_max"][0]

    issues: list[str] = []

    if precipitation >= 1:
        issues.append(f"강수 예상 있음 - 총 강수량 {precipitation}mm")

    if rain >= 1:
        issues.append(f"비 예상 있음 - 비 {rain}mm")

    if snowfall >= 0.5:
        issues.append(f"눈 예상 있음 - 눈 {snowfall}cm")

    if temp_max >= 33:
        issues.append(f"폭염 가능성 있음 - 최고기온 {temp_max}℃")

    if temp_min <= -10:
        issues.append(f"한파 가능성 있음 - 최저기온 {temp_min}℃")

    if wind_max >= 30:
        issues.append(f"바람 강함 - 최대 풍속 {wind_max}km/h")

    if temp_max - temp_min >= 10:
        issues.append(f"일교차 큼 - 최저 {temp_min}℃ / 최고 {temp_max}℃")
    issues.append("테스트 알림 - Slack 연결 확인용")
    return issues


def build_slack_message(issues: list[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "대전 날씨 특이사항 알림",
        "",
        f"날짜 - {today}",
        "",
        *[f"- {issue}" for issue in issues],
    ]

    return "\n".join(lines)


def main() -> int:
    try:
        weather_data = fetch_daejeon_weather()
        issues = judge_special_weather(weather_data)

        if not issues:
            print("No special weather issue today.")
            return 0

        message = build_slack_message(issues)
        send_slack_message(message)

        print("Slack alert sent.")
        return 0

    except requests.RequestException as error:
        print(f"Network error: {error}", file=sys.stderr)
        return 1

    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
