# DE440s asset

[de440s.bsp](https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp)
is retained verbatim in Docker; verified offline at runtime, no download.
SHA-256: `c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2`.
Attribution: [Park et al., AJ 161:105 (2021)](https://ssd.jpl.nasa.gov/doc/de440_de441.html);
[JPL use guidance](https://www.jpl.nasa.gov/jpl-image-use-policy/).

Opt-in centers 10/399/301/199/299; explicit body segments 1→199, 2→299,
no barycenter substitution. Geometric ICRF XYZ, SSB, km, TDB, corrections NONE;
source_epoch/absolute accuracy null. [API contract](../../docs/COORDINATES.md),
[Horizons evidence](../../docs/SOURCE_AUDIT.md).
