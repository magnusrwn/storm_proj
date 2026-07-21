import csv
import logging
import time
from dataclasses import dataclass
import asyncio
from src.utils.helper import RequestWithRetryResponse, request_with_retry
from pathlib import Path
from logger_config import configure_logging


DATA_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = Path(__file__).resolve().parents[2] + "/logs"
AIRPORT_DATA_PATH = DATA_DIR / "airports_sorted.csv"
OUTPUT_CSV = DATA_DIR / "weather_api_responses.csv"

logger = logging.getLogger(__name__)

BASE_API_URL = 'https://archive-api.open-meteo.com/v1/archive'

# NOTE: CEHCK THESE IF NEEDED IN CODE
DAILY_FIELDS = [
    "time",
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "precipitation_sum",
    "rain_sum",
    "showers_sum",
    "snowfall_sum",
    "snow_depth_max",
    "cloud_cover_mean",
    "cloud_cover_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "pressure_msl_mean",
    "visibility_mean",
]

FIELDNAMES = (
    ["latitude", "longitude"]
    + [f"daily_units_{field}" for field in DAILY_FIELDS]
    + [f"daily_{field}" for field in DAILY_FIELDS]
)

@dataclass
class RunStats:
    enqueued: int = 0
    fetch_failed: int = 0
    written: int = 0
    write_failed: int = 0


with open(AIRPORT_DATA_PATH, newline="") as f:
    reader = csv.DictReader(f)
    # Create data rows var
    DATA_ROWS_IN = list(reader)

async def fetch_weather_data(
    queue: asyncio.Queue[RequestWithRetryResponse], date: str, long: str, lat: str, stats: RunStats
):
    url = f"{BASE_API_URL}?latitude={lat}&longitude={long}&start_date={date}&end_date={date}&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_sum,rain_sum,showers_sum,snowfall_sum,snow_depth_max,cloud_cover_mean,cloud_cover_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,pressure_msl_mean,visibility_mean&timezone=auto"

    try:
        response = await request_with_retry(url, "GET")

        await queue.put(response)
        stats.enqueued += 1
    except Exception:
        stats.fetch_failed += 1
        logger.exception(
            "Unexpected fetch error: date=%s latitude=%s longitude=%s",
            date,
            lat,
            long,
        )

async def writer(queue: asyncio.Queue[RequestWithRetryResponse], stats: RunStats):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as file:
        csv_writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        csv_writer.writeheader()
        
        while True:
            item = await queue.get()
            try:
                # Remember the structure of each resposne item from the api.
                # If the response is a straight up error, then add it to the error count to be logged
                if item.error is not None:
                    stats.fetch_failed += 1
                    logger.warning("Skipping failed weather response: %s", item.error)
                    continue
                # if there is no data under the success key, then also add it to the error log count.
                if item.success is None:
                    stats.fetch_failed += 1
                    logger.warning("Skipping weather response with no payload")
                    continue

                payload = item.success
                daily_units = payload.get("daily_units", {})
                daily = payload.get("daily", {})

                # Each request is one date. Extract needed data from API repsonse
                # Build the col.
                row = {
                    "latitude": payload.get("latitude"),
                    "longitude": payload.get("longitude"),
                }
                row.update(
                    {
                        f"daily_units_{field}": daily_units.get(field)
                        for field in DAILY_FIELDS
                    }
                )
                row.update(
                    {
                        f"daily_{field}": values[0]
                        if isinstance(values := daily.get(field), list) and values
                        else values
                        for field in DAILY_FIELDS
                    }
                )

                csv_writer.writerow(row)
                stats.written += 1
            except Exception:
                stats.write_failed += 1
                logger.exception("Could not write weather response to CSV")
            finally:
                queue.task_done()

async def main():
    configure_logging(LOG_DIR/"weather_api.log")
    started_at = time.monotonic()
    queue = asyncio.Queue()
    stats = RunStats()
    logger.info("Starting weather-data run: input_rows=%d output=%s", len(DATA_ROWS_IN), OUTPUT_CSV)

    # Creates and starts tasks.
    fetch_tasks = [
        asyncio.create_task(
            fetch_weather_data(queue, rec["date"], rec["long"], rec["lat"], stats)
        )
        for rec in DATA_ROWS_IN
    ]
    
    # Creates the writer to run async-ly
    writer_task = asyncio.create_task(writer(queue, stats))

    await asyncio.gather(*fetch_tasks)
    # Ensure task count in queue is == 0
    await queue.join()

    # Cancel the writer running
    writer_task.cancel()

    # Ensure the writer is closed
    try:
        # Wait till its done
        await writer_task
    except asyncio.CancelledError as e: # NOTE: Can't this be logged?
        logger.info("Writer cancelled as expected.")
        pass

    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "Weather-data run complete: enqueued=%d written=%d fetch_failed=%d "
        "write_failed=%d elapsed_seconds=%.2f",
        stats.enqueued,
        stats.written,
        stats.fetch_failed,
        stats.write_failed,
        elapsed_seconds,
    )

# Run
asyncio.run(main())
