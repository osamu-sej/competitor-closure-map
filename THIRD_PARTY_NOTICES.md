# Third party notices

The application can store and display records returned by [OpenPOI API](https://docs.openpoiapi.com/). Each observation retains the source record's `licenses` and `attributions`; these must be reviewed when redistributing actual records. OpenPOI combines [Overture Maps](https://docs.overturemaps.org/) and Japan Food Facilities sources, including municipal and national open data. Some Overture-derived places include Foursquare data. The [Foursquare Places NOTICE](https://opensource.foursquare.com/places-notice-txt/) applies to those records as indicated by their returned attribution.

Map style and tiles default to [OpenFreeMap](https://openfreemap.org/). Map data attribution includes [OpenStreetMap contributors](https://www.openstreetmap.org/copyright). The map style can be changed with `NEXT_PUBLIC_MAP_STYLE_URL`; update the attribution shown in the UI for a different provider.

Fixture records and evidence in this repository are fictional and do not derive from OpenPOI.

The map implementation uses [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js), BSD 3-Clause. Its browser worker and shared module are copied into `apps/web/public/` for reliable loading with Next.js. The license text is in [apps/web/public/MAPLIBRE_LICENSE.txt](apps/web/public/MAPLIBRE_LICENSE.txt).
