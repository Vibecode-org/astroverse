# DE440s source asset

`de440s.bsp` was downloaded verbatim from NASA/JPL NAIF:
https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp

SHA-256: `c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2`.
This is a retained offline scientific input, included in the Docker image.
Runtime verifies the digest and never downloads coefficients. JPL/Caltech
attribution: Park et al., AJ 161:105 (2021),
https://ssd.jpl.nasa.gov/doc/de440_de441.html .
NASA data use guidance: https://www.jpl.nasa.gov/jpl-image-use-policy/ .

Centers 10 (Sun), 399 (Earth), 301 (Moon), 199 (Mercury), and 299 (Venus) are exposed.
Barycenters 1/2/3 are never substituted for body centers; Mercury/Venus use
the explicit 1→199 and 2→299 segments. Native geometric
ICRF XYZ in km, origin solar-system barycenter, TDB; no light-time or aberration.
There is no single source epoch for a time-dependent ephemeris. Unknown
per-vector covariance stays null. See `docs/COORDINATES.md` for API limits.
