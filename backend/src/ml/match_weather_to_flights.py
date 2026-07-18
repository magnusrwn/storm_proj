# """Attach daily origin and destination weather to the flight data.

# Open-Meteo returns the latitude/longitude of its weather grid cell, rather
# than the exact coordinates supplied in the request.  ``weather_api_responses``
# therefore cannot be joined directly to ``airports_sorted`` on coordinates.
# This script assigns each weather response to the nearest airport lookup on
# the *same date*, then joins that weather onto the flight's origin and
# destination airport for that date.
# """

from __future__ import annotations # NOTE: wt?
from pathlib import Path
import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_FLIGHTS = DATA_DIR / "flight/flight_data_2024_sample.csv"
DEFAULT_AIRPORTS = DATA_DIR / "/airport/airports_sorted.csv"
DEFAULT_WEATHER = DATA_DIR / "weather/weather_api_responses.csv"
DEFAULT_OUTPUT = DATA_DIR / "output/flight_data_2024_sample_with_weather.csv"

# EARTH_RADIUS_KM = 6_371.0088
# def haversine_km(
#     latitude: float,
#     longitude: float,
#     candidate_latitudes: pd.Series,
#     candidate_longitudes: pd.Series,
# ) -> pd.Series:
#     """Return great-circle distances from one point to candidate points."""
#     lat1 = np.radians(latitude)
#     lon1 = np.radians(longitude)
#     lat2 = np.radians(candidate_latitudes.astype(float))
#     lon2 = np.radians(candidate_longitudes.astype(float))
#     haversine = (
#         np.sin((lat2 - lat1) / 2) ** 2
#         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
#     )
#     return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(haversine))


def map_weather_to_airports(airports: pd.DataFrame, weather: pd.DataFrame, max_distance_km: float) -> pd.DataFrame:
    """Map each weather-grid row to its nearest requested airport on that date."""
    airport_columns = {"date", "ap_code", "lat", "long"}
    weather_columns = {"daily_time", "latitude", "longitude"}
    if missing := airport_columns - set(airports.columns):
        raise ValueError(f"Airport lookup is missing columns: {sorted(missing)}")
    if missing := weather_columns - set(weather.columns):
        raise ValueError(f"Weather data is missing columns: {sorted(missing)}")

    airports = airports.loc[:, ["date", "ap_code", "lat", "long"]].copy()
    airports["date"] = pd.to_datetime(airports["date"]).dt.date
    weather = weather.copy()
    weather["date"] = pd.to_datetime(weather["daily_time"]).dt.date

    matches: list[dict[str, object]] = []
    for date, weather_for_date in weather.groupby("date", sort=False):
        airports_for_date = airports.loc[airports["date"] == date]
        if airports_for_date.empty:
            continue

        # for weather_index, response in weather_for_date.iterrows():
        #     distances = haversine_km(
        #         response["latitude"],
        #         response["longitude"],
        #         airports_for_date["lat"],
        #         airports_for_date["long"],
        #     )
        #     airport_index = distances.idxmin()
        #     distance_km = distances.loc[airport_index]
        #     if distance_km <= max_distance_km:
        #         matches.append(
        #             {
        #                 "weather_index": weather_index,
        #                 "date": date,
        #                 "ap_code": airports_for_date.at[airport_index, "ap_code"],
        #                 "weather_airport_distance_km": distance_km,
        #             }
        #         )

    mapped = pd.DataFrame(matches)
    if mapped.empty:
        raise ValueError("No weather rows could be mapped to an airport lookup.")
    if mapped.duplicated(["date", "ap_code"]).any():
        raise ValueError("Multiple weather rows mapped to the same airport and date.")

    # ``mapped`` already contains the canonical date; avoid pandas adding
    # ``date_x``/``date_y`` suffixes when retaining the API response fields.
    return mapped.merge(
        weather.drop(columns="date"),
        left_on="weather_index",
        right_index=True,
        validate="one_to_one",
    )


def attach_weather(flights: pd.DataFrame, mapped_weather: pd.DataFrame, airport_column: str, prefix: str) -> pd.DataFrame:
    """Join a prefixed copy of mapped weather to one flight-airport column."""
    weather_columns = [
        column
        for column in mapped_weather.columns
        if column not in {"weather_index", "date", "ap_code", "daily_time"}
        and not column.startswith("daily_units_")
    ]
    weather_for_join = mapped_weather.loc[:, ["date", "ap_code", *weather_columns]].copy()
    # Retain the API's date as an auditable value, even though the join itself
    # already requires it to equal ``fl_date``.
    weather_for_join["weather_date"] = mapped_weather["daily_time"]
    weather_for_join = weather_for_join.rename(
        columns={
            "date": "fl_date",
            "ap_code": airport_column,
            "weather_date": f"{prefix}_date",
            **{
                column: (
                    f"{prefix}_match_distance_km"
                    if column == "weather_airport_distance_km"
                    else f"{prefix}_{column.removeprefix('daily_')}"
                )
                for column in weather_columns
            },
        }
    )
    return flights.merge(
        weather_for_join,
        on=["fl_date", airport_column],
        how="left",
        validate="many_to_one",
    )

# def parse_args() -> argparse.Namespace:
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument("--flights", type=Path, default=DEFAULT_FLIGHTS)
#     parser.add_argument("--airports", type=Path, default=DEFAULT_AIRPORTS)
#     parser.add_argument("--weather", type=Path, default=DEFAULT_WEATHER)
#     parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
#     # parser.add_argument(
#     #     "--max-distance-km",
#     #     type=float,
#     #     default=25.0,
#     #     help="Reject weather rows farther than this from their nearest airport (default: 25).",
#     # )
#     return parser.parse_args()


def main() -> None:
    # args = parse_args()
    flights = pd.read_csv()
    flights["fl_date"] = pd.to_datetime(flights["fl_date"]).dt.date
    airports = pd.read_csv()
    weather = pd.read_csv()

    mapped_weather = map_weather_to_airports(airports, weather, args.max_distance_km)
    flights = attach_weather(flights, mapped_weather, "origin", "origin_weather")
    flights = attach_weather(flights, mapped_weather, "dest", "dest_weather")

    # TODO: Write differently/ make pd.Df that will be written in dif way
    # args.output.parent.mkdir(parents=True, exist_ok=True)
    # flights.to_csv(args.output, index=False)

    # TODO: Remake output msgs
    origin_matched = flights["origin_weather_weather_code"].notna().sum()
    destination_matched = flights["dest_weather_weather_code"].notna().sum()
    # print(f"Wrote {len(flights):,} flights to {args.output}")
    # print(
    #     f"Mapped {len(mapped_weather):,} weather rows; "
    #     f"origin weather: {origin_matched:,}; destination weather: {destination_matched:,}."
    # )


if __name__ == "__main__":
    main()
