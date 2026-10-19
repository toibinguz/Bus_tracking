"""
Module 2.2: Route Topological Alignment
Hàn gắn các đoạn Way của OpenStreetMap thành đường cong tim tuyến 1D liên tục,
đảo chiều các way bị ngược và đảm bảo tính liên tục của danh sách tọa độ.
"""

def orient_osm_ways(ways):
    """
    2 chiều hóa các đoạn Way của OSM sao cho điểm cuối của way[i]
    nối khớp liên tục với điểm đầu của way[i+1].
    """
    if not ways:
        return []
    oriented = []
    for i, w in enumerate(ways):
        coords = list(w.get("coordinates", []))
        nids = list(w.get("node_ids", []))
        if i == 0 and len(ways) > 1:
            next_nids = ways[1].get("node_ids", [])
            if next_nids and nids:
                if nids[0] in (next_nids[0], next_nids[-1]) and nids[-1] not in (next_nids[0], next_nids[-1]):
                    coords.reverse()
                    nids.reverse()
        elif i > 0 and nids and oriented[-1].get("node_ids"):
            prev_end = oriented[-1]["node_ids"][-1]
            if nids[-1] == prev_end and nids[0] != prev_end:
                coords.reverse()
                nids.reverse()
        nw = dict(w)
        nw["coordinates"] = coords
        nw["node_ids"] = nids
        oriented.append(nw)
    return oriented

