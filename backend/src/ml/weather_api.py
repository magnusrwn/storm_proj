import json
import csv
import logging
import time
from dataclasses import dataclass
import pandas as pd
import asyncio
from backend.src.utils.helper import request_with_retry

AIRPORT_DATA_PATH = './data/airports_sorted.csv'
BASE_API_URL = 'https://archive-api.open-meteo.com/v1/archive'
OUTPUT_CSV = './data/weather_api_responses.csv'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

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
    queue: asyncio.Queue[dict], date: str, long: str, lat: str, stats: RunStats
):
    url = f"{BASE_API_URL}?latitude={lat}&longitude={long}&start_date={date}&end_date={date}&daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_sum,rain_sum,showers_sum,snowfall_sum,snow_depth_max,cloud_cover_mean,cloud_cover_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,pressure_msl_mean,visibility_mean&timezone=auto"

    try:
        response = await request_with_retry(url, "GET")

        if response.success is not None:
            await queue.put(response.success)
            stats.enqueued += 1
            return

        stats.fetch_failed += 1
        logger.warning(
            "Fetch failed: date=%s latitude=%s longitude=%s error=%s",
            date,
            lat,
            long,
            response.error,
        )
    except Exception:
        stats.fetch_failed += 1
        logger.exception(
            "Unexpected fetch error: date=%s latitude=%s longitude=%s",
            date,
            lat,
            long,
        )

async def writer(queue: asyncio.Queue[dict], stats: RunStats):
    # Keep the full API response until the ML feature columns are decided.  A CSV
    # cell can store JSON, and this keeps the intermediate output lossless.
    fieldnames = ["payload"]

    # `open` is synchronous; that is fine here because each CSV write is tiny.
    # Do not use `async with` because normal files do not implement an async
    # context manager.
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as file:
        csv_writer = csv.DictWriter(file, fieldnames=fieldnames)
        csv_writer.writeheader()
        
        while True:
            item = await queue.get()
            try:
                # Later, replace this with a flattened dict containing the
                # feature columns you choose.
                csv_writer.writerow({"payload": json.dumps(item)})
                stats.written += 1
            except Exception:
                stats.write_failed += 1
                logger.exception("Could not write weather response to CSV")
            finally:
                queue.task_done()


# I WANT TO KEEP: ["daily", "daily_units", "latitude", "longitude"]
async def main():
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
    except asyncio.CancelledError:
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
    


# Runner
asyncio.run(main())
