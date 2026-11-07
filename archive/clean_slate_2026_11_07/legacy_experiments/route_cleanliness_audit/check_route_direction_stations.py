import sqlite3

conn = sqlite3.connect('data/hanoi_bus_system.db')
c = conn.cursor()

c.execute("SELECT route_id, station_id, direction FROM canonical_station_master")
st_dir = {}
for r_id, st_id, d in c.fetchall():
    st_dir[(r_id, st_id)] = d

print("Loaded canonical station directions:", len(st_dir))

for rc in ['BRT01', '02', '22A', '34', 'E04', '26', 'E05']:
    c.execute("SELECT route_id FROM canonical_route_master WHERE route_code = ?", (rc,))
    r_id = c.fetchone()[0]
    
    c.execute("""
        SELECT direction, current_station_id, COUNT(1) 
        FROM vehicle_unique_pings 
        WHERE route_id = ? AND current_station_id > 0 
        GROUP BY direction, current_station_id
    """, (r_id,))
    rows = c.fetchall()
    
    match = {1: {'go': 0, 're': 0}, -1: {'go': 0, 're': 0}}
    for p_dir, st_id, cnt in rows:
        if (r_id, st_id) in st_dir:
            d = st_dir[(r_id, st_id)]
            match[p_dir][d] += cnt
            
    print(f"Route {rc:<6}: Ping  1 -> go:{match[1]['go']:>5}, re:{match[1]['re']:>5} | Ping -1 -> go:{match[-1]['go']:>5}, re:{match[-1]['re']:>5}")

