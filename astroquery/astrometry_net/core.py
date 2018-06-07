"""
==============
Astrometry.net
==============
Given an astropy `astropy.table.Table` as a source list, calculate the astrometric solution.
Before querying astrometry.net you will have to register and obtain an api key from
[http://nova.astrometry.net/].

Sample Use
=========
::

    from astropy.table import Table
    from astroquery.astrometry_net import AstrometryNet

    AstrometryNet.api_key = 'XXXXXXXXXXXXXXXX'

    sources = Table.read('catalog.fits')

    settings = {
        'scale_units': 'arcsecperpix',
        'scale_type': 'ul',
        'scale_lower': 0.20,
        'scale_upper': 0.30,
        'center_ra': 8.711675,
        'center_dec': -78.9810555556,
        'radius': 15,
        'parity': 0
    }

    AstrometryNet.solve(sources, settings, 'X_IMAGE', 'Y_IMAGE', 'FWHM_IMAGE', 'FLAGS', 'FLUX_APER')


Settings
========
In order to speed up the astrometric solution it is possible to pass a dictionary of settings
to `astroquery.AstrometryNet.build_package` or `astroquery.AstrometryNet.build_pacakge`.
If no settings are passed to the build function then a set of default parameters will be
used, although this will increase the time it takes astrometry.net to generate a solution.
It is recommended to at least set the bounds of the pixel scale to a reasonable value.

Most of the following descriptions are taken directly from
[astrometry.net](http://nova.astrometry.net/upload).

Scale
-----
It is important to set the pixel scale of the image as accurate as possible to increase the
speed of astrometry.net. From astrometry.net: "Most digital-camera images are at least 10
degrees wide; most professional-grade telescopes are narrower than 2 degrees."

Several parameters are available to set the pixel scale.

    ``scale_units``
        - Units used by pixel scale variables
        - Possible values:
            * ``arcsecperpix``: arcseconds per pixel
            * ``arcminwidth``: width of the field (in arcminutes)
            * ``degwidth``:width of the field (in degrees)
            * ``focalmm``: focal length of the lens (for 35mm film equivalent sensor)
    ``scale_type``
        - Type of scale used
        - Possible values:
            * ``ul``: Set upper and lower bounds. If ``scale_type='ul'`` the parameters
              ``scale_upper`` and ``scale_lower`` must be set to the upper and lower bounds
              of the pixel scale respectively
            * ``ev``: Set the estimated value with a given error. If ``scale_type='ev'`` the
              parameters ``scale_est`` and ``scale_err`` must be set to the estiimated value
              (in pix) and error (percentage) of the pixel scale.

Parity
------
Flipping an image reverses its "parity". If you point a digital camera at the sky and
submit the JPEG, it probably has negative parity. If you have a FITS image, it probably
has positive parity. Selecting the right parity will make the solving process run faster,
but if in doubt just try both. ``parity`` can be set to the following values:
    - ``0``: positive parity
    - ``1``: negative parity
    - ``2``: try both

Star Positional Error
---------------------
When we find a matching "landmark", we check to see how many of the stars in your field
match up with stars we know about. To do this, we need to know how much a star in your
field could have moved from where it should be.

The unit for positional error is in pixels and is set by the key ``positional_error``.

Limits
------
In order to narrow down our search, you can supply a field center along with a radius.
We will only search in indexes which fall within this area.

To set limits use all of the following parameters:
    ``center_ra``: center RA of the field (in degrees)
    ``center_dec``: center DEC of the field (in degrees)
    ``radius``: how far the actual RA and DEC might be from the estimated values (in degrees)

Tweak
-----
By default we try to compute a SIP polynomial distortion correction with order 2.
You can disable this by changing the order to 0, or change the polynomial order by setting
``tweak_order``.

CRPIX Center
------------
By default the reference point (CRPIX) of the WCS we compute can be anywhere in your image,
but often it's convenient to force it to be the center of the image. This can be set by choosing
``crpix_center=True``.

License and Sharing
-------------------
The Astrometry.net [website](http://nova.astrometry.net/) allows users to upload images
as well as catalogs to be used in generating an astrometric solution, so the site gives
users the choice of licenses for their publically available images. Since the astroquery
astrometry.net api is only uploading a source catalog the choice of ``public_visibility``,
``allow_commercial_use``, and ``allow_modifications`` are not really relevant and can be left
to their defaults, although their settings are described below

Visibility
^^^^^^^^^^
By default all catalogs uploaded are publically available. To change this use the setting
``publicly_visible='n'``.

License
^^^^^^^
There are two parameters that describe setting a license:
    ``allow_commercial_use``:
        Chooses whether or not an image uploaded to astrometry.net is licensed
        for commercial use. This can either be set to ``y``, ``n``, or ``d``, which
        uses the default license associated with the api key.
    ``allow_modifications``:
        Whether or not images uploaded to astrometry.net are allowed to be modified by
        other users. This can either be set to ``y``, ``n``, or ``d``, which
        uses the default license associated with the api key.
"""

# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import print_function

import json

import six
from six import string_types
from astropy.io import fits
from astropy import log

from ..query import BaseQuery
from ..utils import async_to_sync, url_helpers
from . import conf
import time


# export all the public classes and methods
__all__ = ['AstrometryNet', 'AstrometryNetClass']

# declare global variables and constants if any


@async_to_sync
class AstrometryNetClass(BaseQuery):
    """
    Not all the methods below are necessary but these cover most of the common
    cases, new methods may be added if necessary, follow the guidelines at
    <http://astroquery.readthedocs.org/en/latest/api.html>
    """
    URL = conf.server
    TIMEOUT = conf.timeout
    API_URL = url_helpers.join(URL, 'api')

    # These are drawn from http://astrometry.net/doc/net/api.html#submitting-a-url
    _constraints = {
        'allow_commercial_use': {'default': 'd', 'type': str, 'allowed': ('d', 'y', 'n')},
        'allow_modifications': {'default': 'd', 'type': str, 'allowed': ('d', 'y', 'n')},
        'publicly_visible': {'default': 'y', 'type': str, 'allowed': ('y', 'n')},
        'scale_units': {'default': None, 'type': str, 'allowed': ('degwidth', 'arcminwidth', 'arcsecperpix')},
        'scale_type': {'default': None, 'type': str, 'allowed': ('ev', 'ul')},
        'scale_lower': {'default': None, 'type': float, 'allowed': (0,)},
        'scale_upper': {'default': None, 'type': float, 'allowed': (0,)},
        'scale_est': {'default': None, 'type': float, 'allowed': (0,)},
        'scale_err': {'default': None, 'type': float, 'allowed': (0, 100)},
        'center_ra': {'default': None, 'type': float, 'allowed': (0, 360)},
        'center_dec': {'default': None, 'type': float, 'allowed': (-90, 90)},
        'radius': {'default': None, 'type': float, 'allowed': (0,)},
        'downsample_factor': {'default': None, 'type': int, 'allowed': (1,)},
        'tweak_order': {'default': 2, 'type': int, 'allowed': (0,)},
        'use_sextractor': {'default': False, 'type': bool, 'allowed': ()},
        'crpix_center': {'default': None, 'type': bool, 'allowed': ()},
        'parity': {'default': None, 'type': int, 'allowed': (0, 2)},
        'image_width': {'default': None, 'type': int, 'allowed': (0,)},
        'image_height': {'default': None, 'type': int, 'allowed': (0,)},
        'positional_error': {'default': None, 'type': float, 'allowed': (0,)},
    }

    @property
    def api_key(self):
        """ Return the Astrometry.net API key. """
        if not conf.api_key:
            log.error("Astrometry.net API key not in configuration file")
        return conf.api_key

    @api_key.setter
    def api_key(self, value):
        """ Temporarily set the API key. """
        conf.api_key = value

    def __init__(self):
        """ Show a warning message if the API key is not in the configuration file. """
        super(AstrometryNetClass, self).__init__()
        if not conf.api_key:
            log.warning("Astrometry.net API key not found in configuration file")
            log.warning("You need to manually edit the configuration file and add it")
            log.warning(
                "You may also register it for this session with AstrometryNet.key = 'XXXXXXXX'")
        self._session_id = None

    def _login(self):
        if not self.api_key:
            raise RuntimeError('You must set the API key before using this service.')
        login_url = url_helpers.join(self.API_URL, 'login')
        payload = self._contruct_payload({'apikey': self.api_key})
        result = self._request('POST', login_url,
                               data=payload,
                               cache=False)
        result_dict = result.json()
        if result_dict['status'] != 'success':
            raise RuntimeError('Unable to log in to astrometry.net')
        self._session_id = result_dict['session']

    def _contruct_payload(self, settings):
        return {'request-json': json.dumps(settings)}

    def _validate_settings(self, settings):
        """
        Check whether the current settings are consistent with the choices available
        from astrometry.net.
        """

        # Check the types and values
        for key, value in six.iteritems(settings):
            if key not in self._constraints or value is None:
                continue
            if not isinstance(value, self._constraints[key]['type']):
                failed = True
                # Try coercing the type...
                if self._constraints[key]['type'] == float:
                    try:
                        _ = self._constraints[key]['type'](value)
                    except ValueError:
                        pass
                    else:
                        failed = False
                if failed:
                    raise ValueError('Value for {} must be of type {}'.format(key, self._constraints[key]['type']))
            # Switching on the types here...not fond of this, but it works.
            allowed = self._constraints[key]['allowed']
            if allowed:
                if self._constraints[key]['type'] == str:
                    # Allowed values is a list of choices.
                    good_value = value in self._constraints[key]['allowed']
                elif self._constraints[key]['type'] == bool:
                    # bool is easy to check...
                    good_value = isinstance(value, bool)
                else:
                    # Assume the parameter is a number which has a minimum and
                    # optionally a maximum.
                    bounds = self._constraints[key]['allowed']
                    good_value = value > bounds[0]
                    try:
                        good_value = good_value and good_value < bounds[1]
                    except IndexError:
                        # No upper bound to check
                        pass
                if not good_value:
                    raise ValueError('Value {} for {} is invalid. '
                                     'The valid '
                                     'values are {}'.format(value, key, allowed))
        # Check some special cases, in which the presence of one value means
        # others are needed.
        if 'scale_type' in settings:
            scale_type = settings['scale_type']
            if scale_type == 'ev':
                required_keys = ['scale_est', 'scale_err', 'scale_units']
            else:
                required_keys = ['scale_lower', 'scale_upper', 'scale_units']
            good = all(req in settings for req in required_keys)
            if not good:
                raise ValueError('Scale type {} requires '
                                 'values for {}'.format(scale_type, required_keys))

    def solve_from_source_list(self, x=None, y=None,
                               image_width=None, image_height=None,
                               center_ra=None, center_dec=None,
                               radius=None, scale_type=None,
                               scale_units=None, scale_lower=None,
                               scale_upper=None, scale_est=None,
                               scale_err=None, tweak_order=None,
                               crpix_center=None, parity=None
                               ):
        """
        Plate solve from a list of source positions.

        Parameters
        ----------

        x : list-like
            List of x-coordinate of source positions.
        y : list-like
            List of y-coordinate of source positions.
        image_width : int
            Size of the image in the x-direction.
        image_height : int
            Size of the image in the y-direction.
        """
        settings = {
            # 'allow_commercial_use': allow_commercial_use,
            # 'allow_modifications': allow_modifications,
            # 'publicly_visible': publicly_visible,
            'scale_units': scale_units,
            'scale_type': scale_type,
            'scale_lower': scale_lower,
            'scale_upper': scale_upper,
            'scale_est': scale_est,
            'scale_err': scale_err,
            'center_ra': center_ra,
            'center_dec': center_dec,
            'radius': radius,
            # 'downsample_factor': downsample_factor,
            'tweak_order': tweak_order,
            # 'use_sextractor': use_sextractor,
            'crpix_center': crpix_center,
            'parity': parity,
            'image_width': image_width,
            'image_height': image_height,
            # 'positional_error': positional_error,
        }
        if (x is None or y is None or
                image_width is None or image_height is None):
            raise ValueError('Must provide values for x, y, '
                             'image_width and image_height')
        settings = {k: v for k, v in six.iteritems(settings) if v is not None}
        settings['x'] = [float(v) for v in x]
        settings['y'] = [float(v) for v in y]
        self._validate_settings(settings)
        if self._session_id is None:
            self._login()

        settings['session'] = self._session_id
        payload = self._contruct_payload(settings)
        url = url_helpers.join(self.API_URL, 'url_upload')
        response = self._request('POST', url, data=payload, cache=False)
        if response.status_code != 200:
            raise RuntimeError('Post of job failed')
        response_d = response.json()
        submission_id = response_d['subid']
        has_completed = False
        job_id = None
        while not has_completed:
            time.sleep(1)
            sub_stat_url = url_helpers.join(self.API_URL, 'submissions', str(submission_id))
            sub_stat = self._request('GET', sub_stat_url, cache=False)
            jobs = sub_stat.json()['jobs']
            if jobs:
                job_id = jobs[0]
            if job_id:
                job_stat_url = url_helpers.join(self.API_URL, 'jobs', str(job_id), 'info')
                job_stat = self._request('GET', job_stat_url, cache=False)
                has_completed = job_stat.json()['status'] == 'success'
            print(has_completed)
        wcs_url = url_helpers.join(self.URL, 'wcs_file', str(job_id))
        wcs_response = self._request('GET', wcs_url)
        wcs = fits.Header.fromstring(wcs_response.text)
        return wcs


# the default tool for users to interact with is an instance of the Class
AstrometryNet = AstrometryNetClass()

# once your class is done, tests should be written
# See ./tests for examples on this

# Next you should write the docs in astroquery/docs/module_name
# using Sphinx.
