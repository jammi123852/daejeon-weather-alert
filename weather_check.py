import os
import sys
from datetime import datetime
from typing import Any

import requests


DAEJEON_LATITUDE = 36.3504
DAEJEON_LONGITUDE = 127.3845

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

RAIN_THRESHOLD_MM = 0.1
SNOW_THRESHOLD_CM = 0.1
STRONG_RAIN_THRESHOLD_MM = 5.0
STRONG_WIND_THRESHOLD_KMH = 30.0
HOT_THRESHOLD_C = 33.0
COLD_THRESHOLD_C = -10.0


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
        "hourly": [
            "temperature_2m",
            "precipitation",
            "rain",
            "snowfall",
            "wind_speed_10m",
        ],
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
        ],
        "timezone": "Asia/Seoul",
        "forecast_days": 1,
    }

    response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
    response.raise_for_status()

    return response.json()


def parse_hour_text(time_text: str) -> str:
    return datetime.fromisoformat(time_text).strftime("%H:%M")


def make_time_range(start_time: str, end_time: str) -> str:
    start_hour = parse_hour_text(start_time)
    end_dt = datetime.fromisoformat(end_time)
    end_hour = end_dt.strftime("%H:%M")
    return f"{start_hour} - {end_hour}"


def group_consecutive_weather_hours(weather_data: dict[str, Any]) -> list[dict[str, Any]]:
    hourly = weather_data.get("hourly")

    if not hourly:
        raise RuntimeError("Weather response does not contain hourly data.")

    times = hourly["time"]
    precipitation_values = hourly["precipitation"]
    rain_values = hourly["rain"]
    snowfall_values = hourly["snowfall"]
    wind_values = hourly["wind_speed_10m"]
    temperature_values = hourly["temperature_2m"]

    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None

    for index, time_text in enumerate(times):
        precipitation = precipitation_values[index]
        rain = rain_values[index]
        snowfall = snowfall_values[index]
        wind_speed = wind_values[index]
        temperature = temperature_values[index]

        event_types: list[str] = []

        if rain >= RAIN_THRESHOLD_MM:
            event_types.append("비")

        if snowfall >= SNOW_THRESHOLD_CM:
            event_types.append("눈")

        if wind_speed >= STRONG_WIND_THRESHOLD_KMH:
            event_types.append("강풍")

        if temperature >= HOT_THRESHOLD_C:
            event_types.append("폭염")

        if temperature <= COLD_THRESHOLD_C:
            event_types.append("한파")

        if not event_types:
            if current_group is not None:
                groups.append(current_group)
                current_group = None
            continue

        event_key = "+".join(event_types)

        if current_group is None:
            current_group = {
                "event_key": event_key,
                "start_time": time_text,
                "end_time": time_text,
                "precipitation_sum": precipitation,
                "rain_sum": rain,
                "snowfall_sum": snowfall,
                "max_wind": wind_speed,
                "min_temp": temperature,
                "max_temp": temperature,
            }
            continue

        if current_group["event_key"] == event_key:
            current_group["end_time"] = time_text
            current_group["precipitation_sum"] += precipitation
            current_group["rain_sum"] += rain
            current_group["snowfall_sum"] += snowfall
            current_group["max_wind"] = max(current_group["max_wind"], wind_speed)
            current_group["min_temp"] = min(current_group["min_temp"], temperature)
            current_group["max_temp"] = max(current_group["max_temp"], temperature)
        else:
            groups.append(current_group)
            current_group = {
                "event_key": event_key,
                "start_time": time_text,
                "end_time": time_text,
                "precipitation_sum": precipitation,
                "rain_sum": rain,
                "snowfall_sum": snowfall,
                "max_wind": wind_speed,
                "min_temp": temperature,
                "max_temp": temperature,
            }

    if current_group is not None:
        groups.append(current_group)

    return groups


def judge_daily_temperature_issue(weather_data: dict[str, Any]) -> list[str]:
    daily = weather_data.get("daily")

    if not daily:
        raise RuntimeError("Weather response does not contain daily data.")

    temp_max = daily["temperature_2m_max"][0]
    temp_min = daily["temperature_2m_min"][0]

    issues: list[str] = []

    if temp_max - temp_min >= 10:
        issues.append(f"일교차 큼 - 최저 {temp_min:.1f}℃ / 최고 {temp_max:.1f}℃")

    return issues


def format_weather_group(group: dict[str, Any]) -> str:
    event_key = group["event_key"]
    time_range = make_time_range(group["start_time"], group["end_time"])

    details: list[str] = []

    if "비" in event_key:
        details.append(f"비 예보, 강수량 {group['rain_sum']:.1f}mm")

    if "눈" in event_key:
        details.append(f"눈 예보, 적설량 {group['snowfall_sum']:.1f}cm")

    if "강풍" in event_key:
        details.append(f"강풍 가능, 최대 풍속 {group['max_wind']:.1f}km/h")

    if "폭염" in event_key:
        details.append(f"폭염 가능, 최고기온 {group['max_temp']:.1f}℃")

    if "한파" in event_key:
        details.append(f"한파 가능, 최저기온 {group['min_temp']:.1f}℃")

    return f"- {time_range} / " + " / ".join(details)


def build_slack_message(weather_groups: list[dict[str, Any]], daily_issues: list[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "대전 날씨 특이사항 알림",
        "",
        f"날짜 - {today}",
        "",
    ]

    if weather_groups:
        lines.append("시간대별 특이사항")
        for group in weather_groups:
            lines.append(format_weather_group(group))
        lines.append("")

    if daily_issues:
        lines.append("하루 기준 특이사항")
        for issue in daily_issues:
            lines.append(f"- {issue}")

    return "\n".join(lines).strip()


def main() -> int:
    try:
        weather_data = fetch_daejeon_weather()

        weather_groups = group_consecutive_weather_hours(weather_data)
        daily_issues = judge_daily_temperature_issue(weather_data)

        if not weather_groups and not daily_issues:
            message = "대전 날씨 확인 완료\n오늘 특이사항 없음"
            send_slack_message(message)
            print("No special weather issue today. Slack confirmation sent.")
            return 0

        message = build_slack_message(weather_groups, daily_issues)
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
