# Copyright (c) Geoffrey Lentner 2015. All Rights Reserved.
# See LICENSE (GPLv3)
# slipy/SLiPy/Profile.py

"""
Profile fitting tasks for spectra.
"""
import numpy as np
from scipy.optimize import curve_fit
from scipy.interpolate.interpolate import interp1d
from scipy.special import wofz as w

from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib import widgets

from astropy import units as u

from .. import SlipyError
from .Observatory import Observatory
from .Spectrum import Spectrum, SpectrumError
from .Plot import SPlot, PlotError
from ..Framework.Options import Options, OptionsError

from ..Algorithms.Functions import Gaussian, InvertedLorentzian, NormalizedGaussian
from ..Algorithms.KernelFit import KernelFit1D

class ProfileError(SlipyError):
	"""
	Exception specific to Profile module.
	"""
	pass

def Pick(event):
    """
    Used to hand selection events.
    """

    if isinstance(event.artist, Line2D):

        # get the x, y data from the pick event
        thisline = event.artist
        xdata = thisline.get_xdata()
        ydata = thisline.get_ydata()
        ind = event.ind

        # update the selection dictionary
        global selected
        selected['wave'].append(np.take(xdata,ind)[0])
        selected['data'].append(np.take(ydata,ind)[0])

        # display points as a visual aid
        plt.scatter(np.take(xdata,ind)[0], np.take(ydata,ind)[0],
            marker = 'o', s=75, c='r')
        plt.draw()

# empty selection dictionary is filled with the Select() function
selected = {'wave': [], 'data': []}

def Select(splot):
    """
    Select points from the `splot`. This should be of type SPlot
    (or it can optionally be a Spectrum type, for which a SPlot will be
    created). The splot will be rendered and the user clicks on the
    figure. When finished, return to the terminal prompt. A dictionary is
    returned with two entries, `wave` and `data`, representing the x-y
    locations selected by the user. This can always be retrieved later by
    accessing the module member `Profile.selected`.
    """
    if type(splot) is Spectrum:
        splot = SPlot(splot)

    elif type(splot) is not SPlot:
        raise ProfileError('Select() requires either a Spectrum or SPlot '
        'object as an argument')

    # reset the selection dictionary
    global selected
    selected = { 'wave': [], 'data': []}

    splot.draw(picker = True)

    splot.fig.canvas.mpl_connect('pick_event', Pick)

    input(' Press <Return> after making your selections ... ')
    return selected

def Fit(splot, function = InvertedLorentzian, params = None):
    """
    Given `splot` of type SPlot, the user selects two points on the
    spectrum and a parameterized function is fit (an inverted Lorentzian by
    default). Optionally, `splot` can be of type spectrum and a basic SPlot
    will be created for you. If the user gives an alternative `function`,
    `params` (parameters) must be provided. `params` is to be the first guess,
    `p0` given to scipy...curve_fit; the user can provide them expicitely,
    or in the form of functions with the template `function(xarray, yarray)`
    where `xarray` and `yarray` are the `wave` and `data` arrays extracted
    between the two points selected by the user.
    """

    print(' Please select four points identifying the spectral line.')
    print(' Outer points mark the domain of the line.')
    print(' Inner points mark the sample of the line to fit.')

    # make selections
    selected = Select(splot)

    if len( selected['wave'] ) != 4:
        raise ProfileError('Exactly 4 locations should be selected for '
        'the Profile.Fit() routine!')

    # order the selected wavelength locations
    points = selected['wave']
    points.sort()

    # get data and wavelength arrays
    if type(splot) is SPlot:
        wave, data = splot.wave[0], splot.data[0]
    else:
        wave, data = splot.wave, splot.data

    # extract the domains `selected` (i.e., the sample interval)
    x_inner = wave[np.where(np.logical_and(points[1] < wave, wave < points[2]))]
    x_outer = wave[np.where(np.logical_and(points[0] < wave, wave < points[3]))]
    y_inner = data[np.where(np.logical_and(points[1] < wave, wave < points[2]))]
    y_outer = data[np.where(np.logical_and(points[0] < wave, wave < points[3]))]

    # y_inner = data[ wave[ wave < points[2] ] > points[1] ]
    # x_inner = wave[ wave[ wave < points[2] ] > points[1] ]

    if function.__name__ == 'InvertedLorentzian':
        # First guess for default behavior
        params = [ y_inner.min().value, x_inner[ y_inner.argmin() ].value,
            (x_inner[-1] - x_inner[0]).value / 2]

    elif not params:
        # the user gave a different function but not parameters!
        raise ProfileError('The user must provide `params` when giving an '
        'alternative `function` in Profile.Fit()!')

    else:

        if not hasattr(params, '__iter__'):
            raise ProfileError('`params` must be an iterable type in '
            'Profile.Fit()!')

        try:
            for a, parameter in enumerate(params):
                if type(parameter) is type(InvertedLorentzian):
                    # replace parameter with function evaluation
                    params[a] = parameter(x_inner, y_inner)

        except TypeError as err:
            print(' --> TypeError:', err)
            raise ProfileError('Profile.Fit() failed to call user functions '
            'correctly in `params`!')

    # fit a parameterized curve
    coeff, var_matrix = curve_fit(
            function,      # function to call, default is InvertedLorentzian
            x_inner.value, # domain (without units)
            y_inner.value, # data (without units)
            p0 = params    # list of parameters to try as a first guess
        )

    # display visual aids ...
    # evaluation of the fit profile over larger domain
    plt.plot(x_outer, function(x_outer.value, *coeff) * y_outer.unit,
        'b--', linewidth = 4)
    plt.plot(x_inner, function(x_inner.value, *coeff) * y_inner.unit,
        'r-', linewidth = 4)

    # return the larger domain, evaluated and of type Spectrum
    return Spectrum(function(x_outer.value, *coeff) * y_outer.unit, x_outer)


def Extract(splot, kernel = Gaussian, **kwargs):
    """
    Select locations in the `splot` figure, expected to be of type SPlot.
    Exactly four points should be selected. These are used to extract a
    line profile from the spectrum plotted in the splot figure. The inner
    section is used for the line, and the outer selection is used to model
    the continuum; these, respectively, and both returned as Spectrum objects.
    The gap is jumped using 1D interpolation (scipy...interp1d).
    """
    try:

        options = Options( kwargs, {
            'kind'      : 'cubic' , # given to scipy...interp1d for continuum
            'bandwidth' : 0.1*u.nm, # user should provide this!
            'rms'       : False     # measure the RMS of the line, continuum
        })

        kind      = options('kind')
        bandwidth = options('bandwidth')
        rms       = options('rms')

    except OptionsError as err:
        print(' --> OptionsError:', err)
        raise ProfileError('Unrecognized option given to Extract()!')

    print(' Please select four points identifying the spectral line.')
    print(' Outer intervals sample the continuum.')
    print(' Center interval contains the line.')

    # make selections
    selected = Select(splot)

    if len( selected['wave'] ) != 4:
        raise ProfileError('Exactly 4 locations should be selected for '
        'the profile modeling to work!')

    # order the selected wavelength locations
    wave = selected['wave']
    wave.sort()

    # create `line` profile
    xl = splot.wave[0].copy()
    yl = splot.data[0].copy()
    yl = yl[ xl[ xl < wave[2] ] > wave[1] ]
    xl = xl[ xl[ xl < wave[2] ] > wave[1] ]
    line = Spectrum(yl, xl)

    # extract continuum arrays
    xc = splot.wave[0].copy()
    yc = splot.data[0].copy()
    # inside outer-most selections
    yc = yc[ xc[ xc < wave[3] ] > wave[0] ]
    xc = xc[ xc[ xc < wave[3] ] > wave[0] ]
    # keep wavelengths whole domain for later
    xx = xc.copy()
    yy = yc.copy()
    # but not the line
    yc = yc[np.where(np.logical_or(xc < wave[1], xc > wave[2]))]
    xc = xc[np.where(np.logical_or(xc < wave[1], xc > wave[2]))]

    # use `kernel smoothing` to model the continuum
    model = KernelFit1D(xc, yc, kernel = kernel, bandwidth = bandwidth)

    # interpolate to cross `the gap`
    interp = interp1d(xc, model.mean(xc), kind = kind)

    # continuum model outside the line
    cont_outside = interp(xc)

    # continuum inside the line
    cont_inside = interp(xl)

    # continuum model for whole domain
    cont_domain = interp(xx)

    # build a spectrum from the arrays
    continuum = Spectrum(cont_domain, xx)

    # display visual aid
    plt.plot(xx, cont_domain, 'r--', linewidth = 3)
    plt.fill_between(xl, yl, cont_inside, color = 'blue', alpha = 0.25)
    plt.draw()

    if not rms:
        return line, continuum

    cont_rms = np.sqrt( np.sum( (cont_outside * yc.unit - yc)**2 ) / len(yc) )
    line_rms = cont_rms * np.sqrt(cont_inside / yl.value)

    return line, continuum, line_rms

class FittingGUI:
	"""
	Graphical Interface (keeps references alive) for fitting analytical
	profiles to spectral data.
	"""
	def __init__(self, fig, function='Lorentzian', observatory=None,
		resolution=None, **kwargs):
		"""
		Build widget elements based on a spectrum plotted in `fig` (type SPlot).
		`fig` may also be a Spectrum object (for which a SPlot will be
		created).

		Make initial guesses at parameters, render to figure. `LSP` is the
		Line Spread Function from the instrument profile. This is convolved
		with the profile `function`s to be fit. Usually, Lorentzian`s are fit
		to the `line`s. The LSP is not a parameter to be adjusted and is
		instead inforced for a given `Observatory` or `Resolution`. If not
		given `Resolution` explicitely, one is expected to be provided by the
		`Observatory`; one of these must be given.
		"""
		try:

			options = Options( kwargs, {

					'kind'      : 'cubic' , # given to interp1d for continuum
					'bandwidth' : 0.1*u.nm, # user should provide this!
				})

			kind      = options('kind')
			bandwidth = options('bandwidth')

		except OptionsError as err:
			print(' --> OptionsError:', err)
			raise ProfileError('Unrecognized option given to Extract()!')

		if function not in ['Lorentzian', 'Gaussian']:
			raise ProfileError('The only currently implemented functions '
			'for fitting profiles are `Lorentzian` and `Gaussian`!')

		if observatory and not issubclass( type(observatory), Observatory):
			raise ProfileError('FittingGUI() expects `observatory` to '
			'be derived from the Observatory class!')

		if not observatory and not resolution:
			raise ProfileError('FittingGUI() expects either `resolution` or '
			'an `observatory` (with `resolution` as an attribute) to be '
			'provided as a keyword argument!')

		if resolution and observatory and observatory.Resolution != resolution:
			raise ProfileError('From FittingGUI(), you provided both an '
			'`observatory` and a `resolution` but they don`t match!')

		# resolution for the instrument
		self.res = resolution if resolution else observatory.resolution

		# grab and/or create the SPlot
		if isinstance(fig, Spectrum):
			fig = SPlot(fig, marker='k-', label='spectrum')

		elif not isinstance(fig, SPlot):
			raise ProfileError('FittingGUI() expects the `fig` argument to '
			'either be a Spectrum or a SPlot!')

		print('\n We need to extract the lines from the continuum before we '
		'begin the fitting process.')

		# extract the line, continuum, rms from the spectrum
		self.line, self.continuum, self.rms = Extract(fig, bandwidth=bandwidth,
			rms=True)

		print('\n Now select the peaks of each line to be fit.')
		print(' Initial guesses will be made for each line markered.')
		input(' Press <Return> after making your selections ... ')

		# grab all the selected points
		global selected
		points = np.array([
        	[ entry.value for entry in selected['wave'] ],
        	[ entry.value for entry in selected['data'] ]
			])

		# point pairs in ascending order by wavelength
		points = points[:, points[0].argsort()]

		# domain size of the line and the number of components
		self.domainsize = self.line.wave.value[-1] - self.line.wave.value[0]
		self.numlines   = np.shape(points)[1] - 4

		if self.numlines < 1:
			raise ProfileError('FittingGUI() expects at least one line to '
			'be selected for fitting!')

		# initial guesses for parameters given the line locations,
		# containing `L1`, `L2`, etc ... the values of which are themselves
		# dictionaries of parameters (e.g., `FWHM`, `Depth`, etc...) whose values
		# are the initial guesses for those parameters given the location of
		# it`s peak and the number of peaks within the `line`s domain.
		self.Params = {

				'L' + str(line + 1) : self.Parameterize(function, loc)
				for line, loc in enumerate(points[:, 2:-2].T)

			}

		# final spectral line profile is convolution of the LSP and the
		# line profile function. Gaussian on Gaussian, Gaussian on Lorentzian,
		# etc ... Set the functional form given requested profile function
		self.Convolution = self.SetConvolution(function)

		# grab the actual Figure object and it's axis to keep references
		self.fig = fig.fig
		self.ax  = fig.ax

		# refresh image, but keep any changes in axis limits
		fig.xlim( *fig.ax.get_xlim() )
		fig.ylim( *fig.ax.get_ylim() )
		fig.draw()

		# bring up plot to make room for sliders
		plt.subplots_adjust(bottom = 0.35)

		# resample continuum onto line domain
		self.continuum = self.continuum.copy()
		self.continuum.resample(self.line)

		# common domain for plotting, strip units, wavelengths from continuum
		self.x         = self.continuum.wave.value
		self.continuum = self.continuum.data.value

		# add plots of each line, keep dictionary of handles
		self.Component = {

			line : plt.plot(self.x,
				self.continuum - self.Convolution(self.x, **parameters),
				'k--')[0]

			for line, parameters in self.Params.items()
		}

		# add plot of superposition of each component
		self.Combination, = plt.plot(self.x, self.continuum -
			self.SuperPosition(), 'g-')

		# fix the limits on plot
		xmin, xmax = fig.ax.get_xlim()
		ymin, ymax = fig.ax.get_ylim()
		plt.axis([xmin, xmax, ymin, ymax])

		self.Axis = {

			# key : axis     xpos , ypos + dy       , xsize, ysize
			line  : plt.axes([0.15, 0.05 + k * 0.045, 0.5, 0.035],
				axisbg = 'white')

			for k, line in enumerate( self.Params['L1'].keys() )
		}

		self.Slider = {

			# Slider `key` and widget
			param : widgets.Slider(

				self.Axis[param],    # which axis to put slider on
				param,               # name of parameter (and the slider)
				self.Minimum(param), # set the minimum of the slider
				self.Maximum(param), # set the maximum of the slider
				valinit = self.Params['L1'][param] # initial value
			)

			# create a slider for each parameter
			for param in self.Params['L1'].keys()
		}

		# connect sliders to update function
		for slider in self.Slider.values():
			slider.on_changed(self.Update)

		# create axis for radio buttons
		self.RadioAxis = plt.axes([0.75, 0.03, 0.1, 0.2],
			axisbg = 'white', frameon = False)

		# create the radio button widget
		self.Radio = widgets.RadioButtons(self.RadioAxis,
			tuple(['L' + str(i+1) for i in range(self.numlines)]), active = 0)

		# connect the radio button to it's update function
		self.Radio.on_clicked(self.ToggleComponent)

		# set current component as the first line
		self.current_component = 'L1'

	def Parameterize(self, function, loc):
		"""
		Choose the initial parameters of `function` given the peak `loc`.
		"""
		if function == 'Lorentzian':

			return {

					# FWHM of the Lorentzian
					'FWHM': 0.5 * self.domainsize / self.numlines,

					# center of the line
					'Peak': loc[0]
				}

		elif function == 'Gaussian':

			return {

					# FWHM / Ln(2) of Gaussian
					'FWHM': self.domainsize / (0.5 * self.numlines / 4),

					# center of line
					'Peak': loc[0],

					# depth of line of line
					'Depth': self.continuum[ loc[0] ].value - loc[1]
				}

		else:
			raise ProfileError('From FittingGUI.Parameterize(), the only '
			'currently implemented functions are the `Lorentzian` and '
			'the `Gaussian`!')

	def SetConvolution(self, function):
		"""
		Return which convolution result to use given profile function.
		"""
		if function == 'Lorentzian':

			return self.Gaussian_Lorentzian

		elif function == 'Gaussian':

			return self.Gaussian_Gaussian

		else:
			raise ProfileError('From FittingGUI.SetConvolution(), the only '
			'currently implemented functions are the `Lorentzian` and '
			'the `Gaussian`!')

	def Gaussian_Gaussian(self, x, **params):
		"""
		Convolution of the Gaussian LSP on a Gaussian line feature.
		The convolution of two gaussians is also a gaussian.
		"""
		return Gaussian(

				x,

				# Amplitude of the Gaussian
				params['Depth'],

				# center
				params['Peak'],

				# sigma = FWHM / 2 sqrt{2 log 2}
				params['FWHM'] / 2.3548200450309493
			)


	def Gaussian_Lorentzian(self, x, **params):
		"""
		Convolution of the Gaussian LSP on a Lorentzian line feature.
		This is the Voigt profile, and is proportional to the real part
		of the Faddeeva function (slipy.special.wofz)
		"""

		sigma_root_2 = (params['Peak'] / self.res) / (2 * np.sqrt(np.log(2)))
		z = (( x - params['Peak'] ) + 1j * params['FWHM'] ) / sigma_root_2

		return w(z).real / (sigma_root_2 * np.sqrt(np.pi))

	def SuperPosition(self):
		"""
		Superposition of each line component
		"""
		# emtpy result
		combined = np.zeros(np.shape(self.x))

		# additional lines
		for parameters in self.Params.values():
			combined += self.Convolution(self.x, **parameters)

		return combined

	def Minimum(self, param):
		"""
		Set the lower bound on the `param`eter for it's slider.
		"""
		if param == 'Peak':

			return self.x[0]

		elif param == 'FWHM':

			return 0

		elif param == 'Depth':

			return 0

		else:
			raise ProfileError('From FittingGUI.Minimum(), `{}` is not '
			'currently implemented as a parameter to set the minumum '
			'for!'.format(param))

	def Maximum(self, param):
		"""
		Set the upper bound on the `param`eter for it's slider.
		"""
		if param == 'Peak':

			return self.x[-1]

		elif param == 'FWHM':

			return self.domainsize

		elif param == 'Depth':

			return 1.5 * self.continuum.max()

		else:
			raise ProfileError('From FittingGUI.Maximum(), `{}` is not '
			'currently implemented as a parameter to set the maximum '
			'for!'.format(param))

	def Update(self, val):
		"""
		Cycle thru Sliders and update Parameter dictionary. Re-draw graphs.
		"""

		# the currently selected line component
		line = self.current_component

		# update the appropriate parameters in the dictionary
		for parameter, slider in self.Slider.items():
			self.Params[line][parameter] = slider.val

		# update the appropriate graph data, based on new parameters
		self.Component[line].set_ydata(self.continuum -
			self.Convolution(self.x, **self.Params[line]))

		# update the super-imposed graphs
		self.Combination.set_ydata(self.continuum - self.SuperPosition())

		# push updates to graph
		self.fig.canvas.draw_idle()

	def ToggleComponent(self, label):
		"""
		Toggle function for the radio buttons. Switch between line components
		`L1`, `L2`, etc. Update the sliders to reflect changing parameters.
		"""

		# reassign the current component that is selected
		self.current_component = label

		# make current feature bold and the rest regular
		for line in self.Component.keys():
			if line == label:
				self.Component[line].set_linewidth(2)
			else:
				self.Component[line].set_linewidth(1)

		# update the sliders to reflect the current component
		for parameter, slider in self.Slider.items():
			slider.set_val(self.Params[label][parameter])

		# push updates to graph
		self.fig.canvas.draw_idle()
