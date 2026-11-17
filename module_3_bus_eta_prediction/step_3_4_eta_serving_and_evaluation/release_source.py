"""Validate a downloaded ETA release against the local live-route geometry.

This module never refreshes a release or calls HDFS from the serving process.
Existing releases contain baseline/incidents, not a promoted ML model bundle.
"""
from pathlib import Path
import sqlite3

from module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.eta_snapshot import inspect_active


def load_release_source(pointer, catalog_database):
    active = inspect_active(Path(pointer).resolve())
    release = Path(active['release']).resolve()
    database = release / 'baseline.db'
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as baseline, \
            sqlite3.connect(Path(catalog_database).resolve().as_uri() + '?mode=ro', uri=True) as catalog:
        baseline.execute('SELECT route_code,direction,from_station_order,to_station_order,day_type,hour_slot,'
                         'quality_tier,tt_p10_sec,tt_p50_sec,tt_p90_sec,tt_mean_sec,tt_std_sec,segment_length_m '
                         'FROM agg_segment_travel_times LIMIT 0')
        routes = [row[0] for row in baseline.execute(
            'SELECT DISTINCT route_code FROM agg_segment_travel_times ORDER BY route_code'
        )]
        if not routes:
            raise ValueError('release has no baseline routes')
        for route in routes:
            if not isinstance(route, str):
                raise ValueError('release route codes must be strings')
            for table, columns, order in (
                ('canonical_station_master', 'route_id,direction,station_id,station_order,cum_distance_m', 'station_order'),
                ('canonical_shape_master', 'route_id,direction,point_order,lat,lon,cum_distance_m', 'point_order'),
            ):
                sql = f'SELECT {columns} FROM {table} WHERE route_code=? ORDER BY direction,{order}'
                expected = baseline.execute(sql, (route,)).fetchall()
                actual = catalog.execute(sql, (route,)).fetchall()
                if not expected or expected != actual:
                    raise ValueError(f'release/catalog geometry mismatch: {route} {table}')
            ids = {row[0] for row in baseline.execute(
                'SELECT DISTINCT route_id FROM canonical_station_master WHERE route_code=?', (route,)
            )}
            catalog_ids = {row[0] for row in catalog.execute(
                'SELECT route_id FROM canonical_route_master WHERE route_code=?', (route,)
            )}
            if len(ids) != 1 or ids != catalog_ids:
                raise ValueError(f'release/catalog route identity mismatch: {route}')
    return dict(active, baseline_database=str(database), baseline_routes=routes)
