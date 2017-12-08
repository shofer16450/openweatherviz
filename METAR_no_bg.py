from datetime import datetime
import numpy as np
import cartopy.crs as ccrs
import cartopy.feature as feat
import matplotlib.pyplot as plt
import pandas as pd
from metpy.units import units
from siphon.catalog import TDSCatalog
from siphon.ncss import NCSS
from metpy.calc import get_wind_components,  reduce_point_density
from metpy.plots.wx_symbols import current_weather, sky_cover, wx_code_map
from metpy.plots import StationPlot
# Request METAR data from TDS
# os.system(wget -N http://thredds.ucar.edu/thredds/fileServer/nws/metar/
# ncdecoded/files/Surface_METAR_20171130_0000.nc')


def build_query(west=-58.5, east=32, south=42, north=74):
    metar = TDSCatalog('http://thredds.ucar.edu/thredds/catalog/nws/metar/'
                       'ncdecoded/catalog.xml')
    dataset = list(metar.datasets.values())[0]
    print(list(dataset.access_urls))

    # Access netcdf subset and use siphon to request data
    ncss_url = dataset.access_urls['NetcdfSubset']
    ncss = NCSS(ncss_url)
    print(ncss.variables)

    # get current date and time
    now = datetime.utcnow()
    now = datetime(now.year, now.month, now.day, now.hour)

    # build the query
    query = ncss.query()
    query.lonlat_box(west, east, south, north)
    query.time(now)
    query.variables('air_temperature', 'dew_point_temperature', 'wind_speed',
                    'precipitation_amount_hourly', 'hectoPascal_ALTIM',
                    'air_pressure_at_sea_level', 'wind_from_direction',
                    'cloud_area_fraction', 'weather', 'report')
    query.accept('csv')
    return ncss, query


def get_data(ncss, query, density=50000.):
    attempts = 0
    success = False
    while attempts <= 5 and not success:
        try:
            # Get the netcdf dataset
            data = ncss.get_data(query)
            # convert into pandas dataframe
            df = pd.DataFrame(data)
            success = True
        except ValueError:
            attempts += 1
            print('Not the right amount of columns, trying for the {} time'
                  .format(attempts))

    df = df.replace(-99999, np.nan)
    df = df.dropna(how='any', subset=['wind_from_direction', 'wind_speed'])
    df['cloud_area_fraction'] = (df['cloud_area_fraction'] * 8)
    df['cloud_area_fraction'] = df['cloud_area_fraction'].replace(np.nan, 10) \
        .astype(int)
    # Get the columns with strings and decode
    str_df = df.select_dtypes([np.object])
    str_df = str_df.stack().str.decode('utf-8').unstack()
    # Replace decoded columns in PlateCarree
    for col in str_df:
        df[col] = str_df[col]

    return df


def reduce_density(df, dens, projection='EU'):
    if projection == 'GR':
        proj = ccrs.LambertConformal(central_longitude=-35,
                                     central_latitude=65,
                                     standard_parallels=[35])
    else:
        proj = ccrs.LambertConformal(central_longitude=13, central_latitude=47,
                                     standard_parallels=[35])
    # Use the cartopy map projection to transform station locations to the map
    # and then refine the number of stations plotted by setting a 300km radius
    point_locs = proj.transform_points(ccrs.PlateCarree(),
                                       df['longitude'].values,
                                       df['latitude'].values)
    df = df[reduce_point_density(point_locs, dens)]

    return proj, point_locs, df


def plot_map_standard(proj, point_locs, df_t, area='EU', west=-5.5, east=32,
                      south=42, north=62, fonts=18):
    df = df_t
    # Map weather strings to WMO codes, which we can use to convert to symbols
    # Only use the first symbol if there are multiple
    df['weather'] = df['weather'].str.replace('-SG', 'SG')
    df['weather'] = df['weather'].str.replace('FZBR', 'FZFG')
    df['weather'] = df['weather'].str.replace('-BLSN', 'BLSN')
    df['weather'] = df['weather'].str.replace('-DRSN', 'DRSN')
    wx = [wx_code_map[s.split()[0] if ' ' in s else s] for s in df['weather']
          .fillna('')]
    # Get the wind components, converting from m/s to knots as will
    # be appropriate for the station plot.
    u, v = get_wind_components(((df['wind_speed'].values)*units('m/s'))
                               .to('knots'), (df['wind_from_direction'].values)
                               * units.degree)
    cloud_frac = df['cloud_area_fraction']
    # Change the DPI of the resulting figure. Higher DPI drastically improves
    # look of the text rendering.
    plt.rcParams['savefig.dpi'] = 300
    # =========================================================================
    # Create the figure and an axes set to the projection.
    fig = plt.figure(figsize=(20, 16))
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    # # Set up a cartopy feature for state borders.
    state_boundaries = feat.NaturalEarthFeature(category='cultural',
                                                name='admin_0_countries',
                                                scale='10m',
                                                facecolor='#d8dcd6',
                                                alpha=0.5)
    ax.coastlines(resolution='10m', zorder=1, color='black')
    ax.add_feature(state_boundaries, zorder=1, edgecolor='black')
    # ax.add_feature(cartopy.feature.OCEAN, zorder=0)
    # Set plot bounds
    ax.set_extent((west, east, south, north))
    # Start the station plot by specifying the axes to draw on, as well as the
    # lon/lat of the stations (with transform). We also the fontsize to 12 pt.
    stationplot = StationPlot(ax, df['longitude'].values,
                              df['latitude'].values, clip_on=True,
                              transform=ccrs.PlateCarree(), fontsize=fonts)
    # Plot the temperature and dew point to the upper and lower left,
    # respectively, of the center point. Each one uses a different color.
    stationplot.plot_parameter('NW', df['air_temperature'], color='#960056',
                               fontweight='bold', zorder=2000)
    stationplot.plot_parameter('SW', df['dew_point_temperature'],
                               color='#0b8b87', fontweight='bold')
    # More complex ex. uses custom formatter to control how sea-level pressure
    # values are plotted. This uses the standard trailing 3-digits of
    # the pressure value in tenths of millibars.

    stationplot.plot_parameter('NE', df['hectoPascal_ALTIM'],
                               formatter=lambda v: format(10 * v, '.0f')[-3:],
                               color="#2c6fbb")
    # Plot the cloud cover symbols in the center location. This uses the codes
    # made above and uses the `sky_cover` mapper to convert these values to
    # font codes for the weather symbol font.
    stationplot.plot_symbol('C', cloud_frac, sky_cover)
    # Same this time, but plot current weather to the left of center, using the
    # `current_weather` mapper to convert symbols to the right glyphs.
    stationplot.plot_symbol('W', wx, current_weather, fontsize=20)
    # Add wind barbs
    stationplot.plot_barb(u, v, zorder=1000, linewidth=2)
    # Also plot the actual text of the station id. Instead of cardinal
    # directions, plot further out by specifying a location of 2 increments
    # in x and 0 in y.stationplot.plot_text((2, 0), df['station'])
    plt.savefig('/home/sh16450/Desktop/Metar_plots/CURR_METAR_'+area+'.png',
                bbox_inches='tight', transparent="True", pad_inches=0)


if __name__ == '__main__':
    ncss, query = build_query()
    df_tot = get_data(ncss, query)
    proj, point_locs, df = reduce_density(df_tot, 180000)
    plot_map_standard(proj, point_locs, df, area='EU', fonts=15)

    proj, point_locs, df = reduce_density(df_tot, 20000)
    plot_map_standard(proj, point_locs, df, area='AT', west=8.9, east=17.42,
                      south=45.9, north=49.4)

    proj, point_locs, df = reduce_density(df_tot, 90000)
    plot_map_standard(proj, point_locs, df, area='UK', west=-10.1, east=9.4,
                      south=48.64, north=58.4,  fonts=16)

    proj, point_locs, df = reduce_density(df_tot, 80000)
    plot_map_standard(proj, point_locs, df, area='SCANDI_S', west=1, east=32.7,
                      south=54, north=64.5)

    proj, point_locs, df = reduce_density(df_tot, 70000)
    plot_map_standard(proj, point_locs, df, area='SCANDI_N', west=8, east=39.7,
                      south=64, north=72)

    proj, point_locs, df = reduce_density(df_tot, 50000, 'GR')
    plot_map_standard(proj, point_locs, df, area='GR_ICE', west=-58, east=-12,
                      south=57, north=70.5,  fonts=22)
    plt.close('all')
