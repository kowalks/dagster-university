import os

import plotly.express as px
import plotly.io as pio
import pandas as pd
import geopandas as gpd

from dagster_duckdb import DuckDBResource
from dagster import asset

from . import constants
from ..partitions import weekly_partition


@asset(deps=['taxi_trips', 'taxi_zones'])
def manhattan_stats(database: DuckDBResource):
    """Metrics on taxi trips in Manhattan."""
    query = '''
        select
            zones.zone,
            zones.borough,
            zones.geometry,
            count(1) as num_trips,
        from trips
        left join zones on trips.pickup_zone_id = zones.zone_id
        where borough = 'Manhattan' and geometry is not null
        group by zone, borough, geometry
    '''

    with database.get_connection() as conn:
        trips_by_zone = conn.execute(query).fetch_df()

    trips_by_zone['geometry'] = gpd.GeoSeries.from_wkt(trips_by_zone['geometry'])
    trips_by_zone = gpd.GeoDataFrame(trips_by_zone)

    with open(constants.MANHATTAN_STATS_FILE_PATH, 'w') as output_file:
        output_file.write(trips_by_zone.to_json())

@asset(deps=['manhattan_stats'])
def manhattan_map():
    """A map of the number of trips per taxi zone in Manhattan."""
    trips_by_zone = gpd.read_file(constants.MANHATTAN_STATS_FILE_PATH)

    fig = px.choropleth_mapbox(trips_by_zone,
        geojson=trips_by_zone.geometry.__geo_interface__,
        locations=trips_by_zone.index,
        color='num_trips',
        color_continuous_scale='Plasma',
        mapbox_style='carto-positron',
        center={'lat': 40.758, 'lon': -73.985},
        zoom=11,
        opacity=0.7,
        labels={'num_trips': 'Number of Trips'}
    )

    pio.write_image(fig, constants.MANHATTAN_MAP_FILE_PATH)

@asset(deps=['taxi_trips'], partitions_def=weekly_partition)
def trips_by_week(context, database: DuckDBResource):
    """The number of trips per week, aggregated by week."""
    period_to_fetch = context.asset_partition_key_for_output()

    query = f'''
        select
            date_trunc('week', pickup_datetime) as period,
            count(*) as num_trips,
            sum(passenger_count) as passenger_count,
            sum(total_amount) as total_amount,
            sum(trip_distance) as trip_distance
        from trips
        where pickup_datetime >= '{period_to_fetch}'
            and pickup_datetime < '{period_to_fetch}'::date + interval '1 week'
        group by period
    '''

    with database.get_connection() as conn:
        trips = conn.execute(query).fetch_df()

    if os.path.exists(constants.TRIPS_BY_WEEK_FILE_PATH):
        existing = pd.read_csv(constants.TRIPS_BY_WEEK_FILE_PATH)
        existing = existing[existing['period'] != period_to_fetch]
        trips = pd.concat([existing, trips])

    trips.to_csv(constants.TRIPS_BY_WEEK_FILE_PATH, index=False)
