"""Versioned snapshot semantics; no implicit astrometry or time propagation."""

CONTRACT_VERSION = "coordinates/1"


def coordinate_contract():
    return {
        "version": CONTRACT_VERSION,
        "representation": "catalog_snapshot",
        "unit": "ly", "ly_m": 9460730472580800,
        "axes": "x=d*cos(lat)*cos(lon); y=d*sin(lat); z=d*cos(lat)*sin(lon)",
        "axis_handedness": "left", "origin": None,
        "reference_system": None, "source_epoch": None, "time_scale": None, "source": None,
        "evaluated_at": None, "accuracy": None,
        "unknown_values": "null", "simulation_time_supported": False,
        "root_motion": "snapshot_only; time queries rejected; rebuild relocates complete families",
        "frames": {"equatorial": "catalog RA hours / Dec degrees; reference system unspecified",
                   "galactic": "catalog l/b degrees; realization unspecified"},
    }


def snapshot_coordinates(item):
    # Import here so the partitioner can validate contracts before writing.
    from data.sectors import physical_position
    # Existing exoplanet RA/Dec/distance describe the host system, not an
    # independently measured planet center. Parent membership is not position.
    position = physical_position(item) if item.get("scale") != "solar" and not item.get("parent") else None
    synthetic = item.get("source") == "synthetic"
    return {
        "version": CONTRACT_VERSION, "representation": "catalog_snapshot",
        "status": "synthetic" if synthetic else ("unverified" if position else "unknown"),
        "position": list(position[1:]) if position else None,
        "frame": position[0] if position else None,
        "unit": "ly", "reference_system": None, "origin": None,
        "source_epoch": None, "evaluated_at": None, "time_scale": None,
        "source": item.get("source"), "accuracy": None,
        "simulation_position": None,
    }
