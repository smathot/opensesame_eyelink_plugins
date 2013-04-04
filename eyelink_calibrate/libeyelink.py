"""
This file is part of OpenSesame.

OpenSesame is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

OpenSesame is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with OpenSesame.  If not, see <http://www.gnu.org/licenses/>.
"""

# Don't crash if we fail to load pylink, because we may still use dummy mode.
try:
	import pylink
	custom_display = pylink.EyeLinkCustomDisplay
except:
	custom_display = object
	print u'libeyelink: failed to import pylink'

import pygame
from openexp.keyboard import keyboard
from openexp.mouse import mouse
from openexp.canvas import canvas
from openexp.synth import synth
from openexp.exceptions import response_error
from libopensesame import exceptions
import os.path
import array
import math
import tempfile
try:
	import Image
except:
	from PIL import Image

_eyelink = None

class libeyelink:

	MAX_TRY = 100


	def __init__(self, experiment, resolution, data_file=u'default.edf', fg_color=(255, 255, 255), bg_color=(0, 0, 0), saccade_velocity_threshold=35, saccade_acceleration_threshold=9500, force_drift_correct=False):
		"""<DOC>
		Constructor. Initializes the connection to the Eyelink.

		Arguments:
		experiment		--	The experiment object.
		resolution		--	A (width, height) tuple.

		Keyword arguments:

		data_file		--	The name of the EDF file. (default=u'default.edf')
		fg_color		--	The foreground color for the calibration screen. #
							(default=255,255,255)
		bg_color		--	The background color for the calibration screen. #
							(default=0,0,0)
		saccade_velocity_threshold		--	The velocity threshold used for #
											saccade detection. (default=35)
		saccade_acceleration_threshold	--	The acceleration threshold used #
											for saccade detection. #
											(default=9500)
		force_drift_correct				--	Indicates whether drift correction #
											should be enabled. This is useful #
											only for Eyelink 1000 models, for #
											which drift correction is disabled #
											by default. (default=False)							   

		Returns:
		True on connection success and False on connection failure.
		</DOC>"""

		global _eyelink

		stem, ext = os.path.splitext(data_file)
		if len(stem) > 8 or len(ext) > 4:
			raise exceptions.runtime_error( \
				u'The Eyelink cannot handle filenames longer than 8 characters (plus .EDF extension)')

		self.experiment = experiment
		self.data_file = data_file
		self.resolution = resolution
		self.recording = False
		self.cal_beep = True
		self.cal_target_size = 16		
		self.experiment.eyelink_esc_pressed = False
		self.saccade_velocity_treshold = saccade_velocity_threshold
		self.saccade_acceleration_treshold = saccade_acceleration_threshold
		self.eye_used = None
		self.left_eye = 0
		self.right_eye = 1
		self.binocular = 2
		
		# Only initialize the eyelink once
		if _eyelink == None:
			try:
				_eyelink = pylink.EyeLink()
			except Exception as e:
				raise exceptions.runtime_error( \
					u'Failed to connect to the tracker: %s' % e)					

			graphics_env = eyelink_graphics(self.experiment, _eyelink)
			pylink.openGraphicsEx(graphics_env)				
			
		# Optionally force drift correction. For some reason this must be done
		# as (one of) the first thingsm otherwise a segmentation fault occurs.
		if force_drift_correct:
			self.send_command('driftcorrect_cr_disable = OFF')	

		pylink.getEYELINK().openDataFile(self.data_file)
		pylink.flushGetkeyQueue()
		pylink.getEYELINK().setOfflineMode()

		# Notify the eyelink of the display resolution
		self.send_command('screen_pixel_coords =  0 0 %d %d' % ( \
			self.resolution[0], self.resolution[1]))

		# Determine the software version of the tracker
		self.tracker_software_ver = 0
		self.eyelink_ver = pylink.getEYELINK().getTrackerVersion()
		if self.eyelink_ver == 3:
			tvstr = pylink.getEYELINK().getTrackerVersionString()
			vindex = tvstr.find("EYELINK CL")
			self.tracker_software_ver = int(float(tvstr[(vindex + \
				len("EYELINK CL")):].strip()))

		# Some configuration stuff (not sure what the parser and gazemap mean)
		if self.eyelink_ver >= 2:
			self.send_command("select_parser_configuration 0")
			if self.eyelink_ver == 2: #turn off scenelink camera stuff
				self.send_command("scene_camera_gazemap = NO")
		else:
			self.send_command("saccade_velocity_threshold = %d" % \
				self.saccade_velocity_threshold)
			self.send_command("saccade_acceleration_threshold = %s" % \
				self.saccade_acceleration_threshold)

		# Set EDF file contents
		self.send_command( \
			"file_event_filter = LEFT,RIGHT,FIXATION,SACCADE,BLINK,MESSAGE,BUTTON")
		if self.tracker_software_ver >= 4:
			self.send_command( \
				"file_sample_data  = LEFT,RIGHT,GAZE,AREA,GAZERES,STATUS,HTARGET")
		else:
			self.send_command( \
				"file_sample_data  = LEFT,RIGHT,GAZE,AREA,GAZERES,STATUS")

		# Set link data. This specifies which data is sent through the link and
		# thus be used in gaze contingent displays
		self.send_command( \
			"link_event_filter = LEFT,RIGHT,FIXATION,SACCADE,BLINK,BUTTON")
		self.send_command( \
			"link_event_data = GAZE,GAZERES,HREF,AREA,VELOCITY,STATUS")
		if self.tracker_software_ver >= 4:
			self.send_command( \
				"link_sample_data  = LEFT,RIGHT,GAZE,GAZERES,AREA,STATUS,HTARGET")
		else:
			self.send_command( \
				"link_sample_data  = LEFT,RIGHT,GAZE,GAZERES,AREA,STATUS")				

		# Not sure what this means. Maybe the button that is used to end drift
		# correction?
		self.send_command("button_function 5 'accept_target_fixation'")

		# Make sure that we are connected to the eyelink before we start
		# further communication
		if not self.connected():
			raise exceptions.runtime_error( \
				"Failed to connect to the eyetracker")

		# TODO: The code below potentially fixes a bug, but - pending a more
		# thorough understanding - has been disabled to avoid regressions and
		# other problems. Discussions on this issue can be found here:
		# <http://forum.cogsci.nl/index.php?p=/discussion/comment/1161>
		# <https://www.sr-support.com/showthread.php?3208-Event-data-from-the-link-buffer&p=11979>
		#
		# catch pylink bug: pre 1.0.0.28, calling getfloatData() on
		# start_saccade data returns scrambled events so compare current
		# version to up-to-date version
		#cur_v = pylink.version.vernum
		#utd_v = (1, 0, 0, 28)

		#utd = True
		#for n in range( len(utd_v) ):
			#if cur_v[n] < utd_v[n]:
				#utd = False
			#if utd == False or cur_v[n] > utd_v[n]:
				#break

		## if not  up to date, redefine wait_for_saccade_start
		#if not utd:
			#self.wait_for_saccade_start = self.__wait_for_saccade_start_pre_10028

	def send_command(self, cmd):

		"""<DOC>
		Sends a command to the eyelink.

		Arguments:
		cmd		--	The eyelink command to be executed.
		</DOC>"""

		pylink.getEYELINK().sendCommand(cmd)

	def log(self, msg):

		"""<DOC>
		Writes a message to the eyelink data file.

		Arguments:
		msg		--	The message to be logged.
		</DOC>"""
		
		# sendMessage() is not Unicode safe, so we need to strip all Unicode
		# characters from the message
		if type(msg) == unicode:
			msg = msg.encode('ascii','ignore')
		if type(msg) == str:
			msg = msg.decode('ascii','ignore')
		pylink.getEYELINK().sendMessage(msg)

	def log_var(self, var, val):

		"""<DOC>
		Writes a variable to the eyelink data file. This is a shortcut for #
		eyelink.log("var %s %s" % (var, val)).

		Arguments:
		var		-- The variable name.
		val		-- The value.
		</DOC>"""

		pylink.getEYELINK().sendMessage("var %s %s" % (var, val))

	def status_msg(self, msg):

		"""<DOC>
		Sets the eyelink status message, which is displayed on the eyelink #
		experimenter pc.

		Arguments:
		msg		--	The status message.
		</DOC>"""

		pylink.getEYELINK().sendCommand("record_status_message '%s'" % msg)

	def connected(self):

		"""<DOC>
		Returns the status of the eyelink connection.

		Returns:
		True if connected, False otherwise.
		</DOC>"""

		return pylink.getEYELINK().isConnected()

	def calibrate(self, beep=True, target_size=16):

		"""<DOC>
		Starts eyelink calibration.

		Keyword arguments:
		beep			--	Indicates whether or not the calibration target #
							should beep when jumping. (default=True)
		target_size		--	The size of the calibration target. (default=16)

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		if self.recording:
			raise exceptions.runtime_error( \
				u'Trying to calibrate after recording has started')

		self.cal_beep = beep
		self.cal_target_size = target_size

		# attempt calibrate; confirm abort when esc pressed
		while True:
			pylink.getEYELINK().doTrackerSetup()
			if not self.experiment.eyelink_esc_pressed: 
				break
			else:
				self.confirm_abort_experiment()
				self.experiment.eyelink_esc_pressed = False


	def get_eyelink_clock_async(self):

		"""<DOC>
		Retrieve difference between tracker time (as found in tracker #
		timestamps) and experiment time.

		Returns:
		The tracker time minus experiment time.
		</DOC>"""

		return pylink.getEYELINK().trackerTime() \
					- self.experiment.time()

	def drift_correction(self, pos=None, fix_triggered=False):

		"""<DOC>
		Performs drift correction and falls back to the calibration screen if #
		necessary. Pressing the 'escape' key during drift-correction will not #
		immediately abort the experiment, but will ask for confirmation first.

		Note: This function is simply a wrapper around #
		`fix_triggered_drift_correction()` and `manual_drift_correction()`.

		Keyword arguments:
		pos				--	The coordinates (x,y tuple) for drift correction #
							or None for the display center. (default=None)
		fix_triggered	--	A boolean indicating whether drift correction #
							should be fixation triggered, rather than spacebar #
							triggered. (default=False)

		Returns:
		True on success, False on failure.

		Exceptions:
		Raises an exceptions.runtime_error on error.
		</DOC>"""
		
		self.experiment.eyelink_esc_pressed = False
		if self.recording:
			raise exceptions.runtime_error( \
				u'Trying to do drift correction after recording has started')
		if fix_triggered:
			return self.fix_triggered_drift_correction(pos)
		return self.manual_drift_correction(pos)

	def prepare_drift_correction(self, pos):

		"""<DOC>
		Puts the tracker in drift-correction mode.

		Arguments:
		pos		--	The reference point.

		Exceptions:
		Raises an exceptions.runtime_error on error.
		</DOC>"""

		# Start collecting samples in drift correction mode
		self.send_command("heuristic_filter = ON")
		self.send_command("drift_correction_targets = %d %d" % pos)
		self.send_command("start_drift_correction data = 0 0 1 0")
		pylink.msecDelay(50)
		# Wait for a bit until samples start coming in (I think?)
		if not pylink.getEYELINK().waitForBlockStart(100, 1, 0):
			raise exceptions.runtime_error( \
				u'Failed to perform drift correction (waitForBlockStart error)')

	def fix_triggered_drift_correction(self, pos=None, min_samples=30, max_dev=60, reset_threshold=10):

		"""<DOC>
		Performs fixation triggered drift correction. You can return to the #
		set-up screen by pressing the 'q' key. Pressing the 'escape' key #
		during drift-correction will not immediately abort the experiment, but #
		will ask for confirmation first.

		Keyword arguments:
		pos				--	The coordinate (x,y tuple) for drift correction #
							or None for the display center. (default=None)
		min_samples		--	The minimum nr of stable samples that should be #
							acquired. (default=30)
		max_dev			--	The maximum allowed deviation. (default=60)
		reset_threshold	--	The maximum allowed deviation from one sample to #
							the next (default=10)

		Returns:
		True on success, False on failure.

		Exceptions:
		Raises an exceptions.runtime_error on error or on confirming 'abort #
		experiment'.
		</DOC>"""

		if self.recording:
			raise exceptions.runtime_error( \
				u'Trying to do drift correction after recording has started')
		self.recording = True
		if pos == None:
			pos = self.resolution[0] / 2, self.resolution[1] / 2
		self.prepare_drift_correction(pos)
		my_keyboard = keyboard(self.experiment, keylist=[u'escape', u'q'], \
			timeout=0)
		# Loop until we have sufficient samples
		lx = []
		ly = []
		while len(lx) < min_samples:
			# Pressing escape enters the calibration screen
			try:
				key,time = my_keyboard.get_key()
			except response_error:
				# self.experiment.eyelink_esc_pressed = True
				self.confirm_abort_experiment()
				# self.experiment.eyelink_esc_pressed = False
				self.recording = False
				return False
			else:
				if key != None: # i.e. 'q' was pressed
					self.recording = False
					print u'libeyelink.fix_triggered_drift_correction(): \'q\' pressed'
					return False
			# Collect a sample
			x, y = self.sample()
			if len(lx) == 0 or x != lx[-1] or y != ly[-1]:
				# If the current sample deviates too much from the previous one,
				# reset counting
				if len(lx) > 0 and (abs(x - lx[-1]) > reset_threshold or abs(y - ly[-1]) > reset_threshold):
					lx = []
					ly = []
				# Collect samples
				else:
					lx.append(x)
					ly.append(y)
			if len(lx) == min_samples:
				avg_x = sum(lx) / len(lx)
				avg_y = sum(ly) / len(ly)
				d = math.sqrt( (avg_x - pos[0]) ** 2 + (avg_y - pos[1]) ** 2)
				# Emulate a spacebar press on success
				pylink.getEYELINK().sendKeybutton(32, 0, pylink.KB_PRESS)
				# getCalibrationResult() returns 0 on success and an exception
				# or a non-zero value otherwise
				result = -1
				try:
					result = pylink.getEYELINK().getCalibrationResult()
				except:
					lx = []
					ly = []
					print u'libeyelink.fix_triggered_drift_correction(): try again'
				if result != 0:
					lx = []
					ly = []
					print u'libeyelink.fix_triggered_drift_correction(): try again'
		# Apply drift correction
		pylink.getEYELINK().applyDriftCorrect()
		self.recording = False
		print u'libeyelink.fix_triggered_drift_correction(): success'
		return True

	def manual_drift_correction(self, pos=None):
		
		"""<DOC>
		Performs manual (spacebar-triggered) drift correction. You can return #
		to the set-up screen by pressing the 'q' key. Pressing the 'escape' #
		key during drift-correction will not immediately abort the experiment, #
		but will ask for confirmation first.

		Keyword arguments:
		pos		--	The coordinate (x,y tuple) for drift correction dot or #
					None for the display center. (default=None)

		Returns:
		True on success, False on failure.

		Exceptions:
		Raises an exceptions.runtime_error on error or on confirming 'abort #
		experiment'.
		</DOC>"""

		if pos == None:
			pos = self.resolution[0] / 2, self.resolution[1] / 2
		# ensure eyelink connection before attempting DC
		if not self.connected():
			raise exceptions.runtime_error(u'The eyelink is not connected')
		# attempt drift correction
		try:
			# Params: x, y, draw fix, allow_setup
			error = pylink.getEYELINK().doDriftCorrect(pos[0], pos[1], 0, 0)
			if error != 27: # successful DC
				print u'libeyelink.drift_correction(): success'
				return True
			else: # aborted by Esc or Q
				print u'libeyelink.drift_correction(): escape pressed'
				if not self.experiment.eyelink_esc_pressed:
					return False 
		except: # drift correction failed
			print u'libeyelink.drift_correction(): try again'
			if not self.experiment.eyelink_esc_pressed:
					return False
		# if we get here, it means esc was pressed:
		self.confirm_abort_experiment()
		self.experiment.eyelink_esc_pressed = False
		return False

	def start_recording(self):

		"""<DOC>
		Starts recording of gaze samples.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		self.recording = True
		i = 0
		while True:
			# Params: write  samples, write event, send samples, send events
			error = pylink.getEYELINK().startRecording(1, 1, 1, 1)
			if not error:
				break
			if i > self.MAX_TRY:
				raise exceptions.runtime_error( \
					u'Failed to start recording (startRecording error)')
			i += 1
			print u'libeyelink.start_recording(): failed to start recording (attempt %d of %d)' \
				% (i, self.MAX_TRY)
			pylink.msecDelay(100)
		# Don't know what this is
		pylink.pylink.beginRealTimeMode(100)
		# Wait for a bit until samples start coming in (I think?)
		if not pylink.getEYELINK().waitForBlockStart(100, 1, 0):
			raise exceptions.runtime_error( \
				u'Failed to start recording (waitForBlockStart error)')

	def stop_recording(self):

		"""<DOC>
		Stops recording of gaze samples.
		</DOC>"""

		self.recording = False
		pylink.endRealTimeMode()
		pylink.getEYELINK().setOfflineMode()
		pylink.msecDelay(500)

	def close(self):

		"""<DOC>
		Closes the connection with the eyelink.
		</DOC>"""

		if self.recording:
			self.stop_recording()
		# Close the datafile and transfer it to the experimental pc
		print u'libeyelink: closing data file'
		pylink.getEYELINK().closeDataFile()
		pylink.msecDelay(100)
		print u'libeyelink: transferring data file'
		pylink.getEYELINK().receiveDataFile(self.data_file, self.data_file)
		pylink.msecDelay(100)
		print u'libeyelink: closing eyelink'
		pylink.getEYELINK().close()
		pylink.msecDelay(100)

	def set_eye_used(self):

		"""<DOC>
		Sets the eye_used variable, based on the eyelink's report, which #
		specifies which eye is being tracked. If both eyes are being tracked, #
		the left eye is used.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		<DOC>"""

		self.eye_used = pylink.getEYELINK().eyeAvailable()
		if self.eye_used == self.right_eye:
			self.log_var("eye_used", "right")
		elif self.eye_used == self.left_eye or self.eye_used == self.binocular:
			self.log_var("eye_used", "left")
			self.eye_used = self.left_eye
		else:
			raise exceptions.runtime_error( \
				u'Failed to determine which eye is being recorded')

	def sample(self):

		"""<DOC>
		Gets the most recent gaze sample.

		Returns:
		A tuple (x, y) containing the coordinates of the sample. The value #
		(-1, -1) indicates missing data.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		if not self.recording:
			raise exceptions.runtime_error( \
				u'Please start recording before collecting eyelink data')
		if self.eye_used == None:
			self.set_eye_used()
		s = pylink.getEYELINK().getNewestSample()
		if s == None:
			gaze = -1, -1
		elif self.eye_used == self.right_eye and s.isRightSample():
			gaze = s.getRightEye().getGaze()
		elif self.eye_used == self.left_eye and s.isLeftSample():
			gaze = s.getLeftEye().getGaze()
		else:
			gaze = -1, -1
		return gaze

	def pupil_size(self):

		"""<DOC>
		Gets the most recent pupil size.

		Returns:
		A float corresponding to the pupil size (in arbitrary units). The #
		value -1 indicates missing data.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		if not self.recording:
			raise exceptions.runtime_error( \
				u'Please start recording before collecting eyelink data')
		if self.eye_used == None:
			self.set_eye_used()
		s = pylink.getEYELINK().getNewestSample()
		if s == None:
			ps = -1
		elif self.eye_used == self.right_eye and s.isRightSample():
			ps = s.getRightEye().getPupilSize()
		elif self.eye_used == self.left_eye and s.isLeftSample():
			ps = s.getLeftEye().getPupilSize()
		else:
			ps = -1
		return ps

	def wait_for_event(self, event):

		"""<DOC>
		Waits until an event has occurred.

		Arguments:
		event	-- An EyeLink event, such as pylink.STARTSACC.

		Returns:
		A tuple (timestamp, event). The event is in float_data format. The #
		timestamp is in experiment time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		if not self.recording:
			raise exceptions.runtime_error( \
				u'Please start recording before collecting eyelink data')
		if self.eye_used == None:
			self.set_eye_used()
		t_0 = self.experiment.time()
		while True:
			d = 0
			while d != event:
				d = pylink.getEYELINK().getNextData()
			# ignore d if its event occured before t_0:
			float_data = pylink.getEYELINK().getFloatData()
			if float_data.getTime() - self.get_eyelink_clock_async() > t_0:
				break
		return float_data.getTime() - self.get_eyelink_clock_async(), float_data

	def wait_for_saccade_start(self):

		"""<DOC>
		Waits for a saccade start.

		Returns:
		A (time, start_pos) tuple with timestamp in experiment time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.STARTSACC)
		return t, d.getStartGaze()

	def __wait_for_saccade_start_pre_10028(self):

		"""
		Waits for a saccade start, see wait_for_saccade_start. This
		implementation catches a pylink bug that existed before pylink 1.0.0.28.
		This function is currently not used, see the comments in __init__().
		"""

		t, d = self.wait_for_event(pylink.STARTSACC)
		return t, ( d.getStartGaze()[1], d.getHref()[0] )


	def wait_for_saccade_end(self):

		"""<DOC>
		Waits for a saccade end.

		Returns:
		A (timestamp, start_pos, end_pos) tuple with timestamp in experiment #
		time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.ENDSACC)
		return t, d.getStartGaze(), d.getEndGaze()

	def wait_for_fixation_start(self):

		"""<DOC>
		Waits for a fixation start.

		Returns:
		A (timestamp, start_pos) tuple with timestamp in experiment time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.STARTFIX)
		return t, d.getStartGaze()


	def wait_for_fixation_end(self):

		"""<DOC>
		Waits for a fixation end.

		Returns:
		A (timestamp, start_pos, end_pos) tuple with timestamp in experiment #
		time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.ENDFIX)
		return t, d.getStartGaze(), d.getEndGaze()

	def wait_for_blink_start(self):

		"""<DOC>
		Waits for a blink start.

		Returns:
		A timestamp in experiment time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.STARTBLINK)
		return t

	def wait_for_blink_end(self):

		"""<DOC>
		Waits for a blink end.

		Returns:
		A timestamp in experiment time.

		Exceptions:
		Raises an exceptions.runtime_error on failure.
		</DOC>"""

		t, d = self.wait_for_event(pylink.ENDBLINK)
		return t

	def confirm_abort_experiment(self):
	
		"""
		Asks for confirmation before aborting the experiment. Displays a #
		confirmation screen, collects the response, and acts accordingly.

		Exceptions:
		Raises a response_error upon confirmation.

		Returns:
		False if no confirmation was given.
		"""
		
		# Display the confirmation screen
		conf_canvas = canvas(self.experiment)
		conf_kb = keyboard(self.experiment, timeout=None)
		yc = conf_canvas.ycenter()
		ld = 40
		conf_canvas.clear()
		conf_canvas.text(u'Really abort experiment?', y=yc-3*ld)
		conf_canvas.text(u'Press \'Y\' to abort', y=yc-0.5*ld)
		conf_canvas.text(u'Press any other key or wait 5s to go to setup', \
			y = yc+0.5*ld)
		conf_canvas.show()
		# process the response:
		try:
			key, time = conf_kb.get_key(timeout=5000)
		except:
			return False
		# if confirmation, close experiment
		if key == u'y':
			raise exceptions.runtime_error(u'The experiment was aborted')
		else:
			return False

	def prepare_backdrop(self, canvas):

		"""<DOC>
		Converts a surface to the format required by the eyelink. WARNING: #
		this function can take between 50-150 ms to complete, depending on the #
		resolution of the image and the cpu power of your machine. Do not use #
		during time critical phases of your experiment.

		Arguments:
		canvas		--	An openexp.canvas.

		Returns:
		A (image, width, height) tuple, where image is a #
		pygame.surfarray.array2d.
		</DOC>"""

		if self.experiment.canvas_backend != u'legacy':
			raise exceptions.runtime_error( \
				u'prepare_backdrop requires the legacy back-end')
		return (pygame.surfarray.array2d(canvas.surface).transpose().tolist(), \
			self.experiment.width, self.experiment.height)

	def set_backdrop(self, backdrop):

		"""<DOC>
		Sets backdrop image for the EyeLink computer. For better performance, #
		it can be useful to convert the canvas to send to the eyelink in the #
		prepare phase using eyelink.prepare_backdrop(). If speed is not an #
		issue, you can also directly pass a openexp.canvas object and this #
		function will take care of the conversion.

		WARNING: this function can take between 10-50 ms to complete, #
		depending on the resolution of the image and the cpu power of your #
		machine. Do not use during time critical phases of your experiment.

		Arguments:
		backdrop	--	An openexp.canvas or a tuple representation as #
						returned by prepare_backdrop().

		Returns:
		The amount of time in ms the function took to complete.
		</DOC>"""
		
		starttime = self.experiment.time()

		# For now only the legacy backend will be supported
		# Future releases will support all backends
		if self.experiment.canvas_backend != u'legacy':
			raise exceptions.runtime_error( \
				u'set_backdrop for now requires the legacy back-end')

		# backdrop argument needs to be a canvas or tuple object: if not raise
		# an exception
		if type(backdrop) not in [tuple, canvas]:
			raise exceptions.runtime_error( \
				u'Invalid backdrop argument: needs to be a openexp.canvas or a tuple(list,width,height) object')

		# If backdrop argument is a canvas, first convert it to the required
		# list representation
		if type(backdrop) == canvas:
			backdrop = self.prepare_backdrop(backdrop)

		# If the backdrop argument is tuple containing the list representation,
		# send it to the eyelink (also works for the canvas that just got
		# converted)
		if type(backdrop) == tuple:
			# Check if tuple has correct format
			if len(backdrop) != 3 or type(backdrop[0]) != list or \
				type(backdrop[1]) != int or type(backdrop[2]) != int:
				raise exceptions.runtime_error( \
					u'Invalid tuple; needs to be (array2d.image,width,height)')
			else:
				el = pylink.getEYELINK()

				# "Forward" compatibility
				# In the current unofficial version of pylink, the function that
				# transfers a 2D array list representation to the host PC is
				# called bitmap2DBackdrop. According to the dev team, this
				# function will be integrated with the old bitmapBackdop
				# function again and the bitmap2DBackdrop function will
				# disappear. The following check is to make sure the
				# set_backdrop function will not break.
				if hasattr(el,"bitmap2DBackdrop"):
					send_backdrop = el.bitmap2DBackdrop
				else:
					send_backdrop = el.bitmapBackdrop
				send_backdrop = el.bitmap2DBackdrop
				img = backdrop[0]
				width = backdrop[1]
				height = backdrop[2]
				send_backdrop(width,height,img,0,0,width,height,0,0,pylink.BX_MAXCONTRAST)
		else:
			raise exceptions.runtime_error(u'Unable to send backdrop')
		return self.experiment.time() - starttime

class libeyelink_dummy:

	"""A dummy class to keep things running if there is no tracker attached."""

	def __init__(self, experiment, resolution, data_file="default.edf", fg_color=(255, 255, 255), bg_color=(0, 0, 0), saccade_velocity_threshold=35, saccade_acceleration_threshold=9500):

		"""Initializes the eyelink dummy object"""

		self.experiment = experiment
		self.data_file = data_file
		self.resolution = resolution
		self.recording = False

		self.simulator = mouse(self.experiment)
		self.simulator.set_timeout(timeout=2)

		self.blinking = False # current 'blinking' condition (MOUSEBUTTONDOWN = eyes closed; MOUSEBUTTONUP = eyes open)
		self.bbpos = (resolution[0]/2,resolution[1]/2) # before 'blink' position

		# check if blinking functionality is possible
		if not hasattr(self.simulator, 'get_pressed') or not hasattr(self.simulator, 'set_poesje'):
			print("libeyelink_dummy: blink functionality not available due to missing openexp.mouse.get_pressed and/or openexp.mouse.set_pos methods")
			self.blinkfun = False
		else:
			self.blinkfun = True

	def send_command(self, cmd):

		"""Dummy command"""

		print 'libeyelink.send_command(): %s' % cmd

	def log(self, msg):

		"""Dummy log message"""

		print 'libeyelink.log(): %s' % msg

	def log_var(self, var, val):

		"""Dummy variable logging"""

		print 'libeyelink.log_var(): %s %d' % var, val

	def status_msg(self, msg):

		"""Dummy status message"""

		print 'libeyelink.status_msg(): %s' % msg

	def connected(self):

		"""Dummy connection status"""

		return True

	def calibrate(self, beep=True, target_size=16):

		"""Dummy calibration"""

		print 'libeyelink.calibrate(): calibration would now take place'

	def get_eyelink_clock_async(self):

		"""Asynchronity between libeyelink_dummy object and OpenSesame"""

		return 0

	def drift_correction(self, pos = None, fix_triggered = False):

		"""Dummy drift correction"""

		if fix_triggered:
			return self.fix_triggered_drift_correction(pos)

		self.simulator.set_visible(visible=True)

		my_keyboard = keyboard(self.experiment, keylist=["space"], timeout=0)
		errorbeep = synth(self.experiment, freq=220, length=200)

		if pos == None:
			pos = self.resolution[0] / 2, self.resolution[1] / 2

		errdist = 60 # pixels (on a 1024x768px and 39.9x29.9cm monitor at 67 cm, this is about 2 degrees of visual angle)

		pressed = None
		while not pressed:
			pressed, presstime = my_keyboard.get_key()
			if pressed:
				gazepos = self.sample()
				if ((gazepos[0]-pos[0])**2  + (gazepos[1]-pos[1])**2)**0.5 < errdist:
					self.simulator.set_visible(visible=False)
					return True
		errorbeep.play()
		self.simulator.set_visible(visible=False)
		return False

	def prepare_drift_correction(self, pos):

		"""Dummy drift correction preparation"""

		pass

	def fix_triggered_drift_correction(self, pos = None, min_samples = 30, max_dev = 60, reset_threshold = 10):

		"""Dummy drift correction (fixation triggered)"""

		self.simulator.set_visible(visible=True)

		if pos == None:
			pos = self.resolution[0] / 2, self.resolution[1] / 2

		self.prepare_drift_correction(pos)
		my_keyboard = keyboard(self.experiment, keylist=["escape", "q"], timeout=0)

		# loop until we have sufficient samples
		lx = []
		ly = []
		while len(lx) < min_samples:

			# pressing escape enters the calibration screen
			if my_keyboard.get_key()[0] != None:
				self.simulator.set_visible(visible=False)
				self.recording = False
				print("libeyelink.fix_triggered_drift_correction(): 'q' pressed")
				return False

			# collect a sample
			x, y = self.sample()

			if len(lx) == 0 or x != lx[-1] or y != ly[-1]:

				# if present sample deviates too much from previous sample, reset counting
				if len(lx) > 0 and (abs(x - lx[-1]) > reset_threshold or abs(y - ly[-1]) > reset_threshold):
					lx = []
					ly = []

				# collect samples
				else:
					lx.append(x)
					ly.append(y)

			if len(lx) == min_samples:

				avg_x = sum(lx) / len(lx)
				avg_y = sum(ly) / len(ly)
				d = ((avg_x - pos[0]) ** 2 + (avg_y - pos[1]) ** 2)**0.5

				if d < max_dev:
					self.simulator.set_visible(visible=False)
					return True
				else:
					lx = []
					ly = []

	def start_recording(self):

		"""Start dummy recording"""

		self.simulator.set_visible(visible=True)
		self.recording = True
		print 'libeyelink.start_recording(): recording started'

	def stop_recording(self):

		"""Stop dummy recording"""

		self.simulator.set_visible(visible=False)
		self.recording = False
		print 'libeyelink.stop_recording(): recording stopped'

	def close(self):

		"""Start dummy recording"""

		if self.recording:
			self.stop_recording()

		print 'libeyelink.close(): connection closed'

	def set_eye_used(self):
		pass

	def sample(self):

		"""Returns simulated gaze position (=mouse position)"""

		if self.blinkfun:
			if self.blinking:
				if self.simulator.get_pressed()[2]: # buttondown
					self.simulator.set_pos(pos=(self.bbpos[0],self.resolution[1])) # set position to blinking position
				elif not self.simulator.get_pressed()[2]: # buttonup
					self.simulator.set_pos(pos=self.bbpos) # set position to position before blinking
					self.blinking = False # 'blink' stopped

			elif not self.blinking:
				if self.simulator.get_pressed()[2]: # buttondown
					self.blinking = True # 'blink' started
					self.bbpos =  self.simulator.get_pos()[0] # position before blinking
					self.simulator.set_pos(pos=(self.bbpos[0],self.resolution[1])) # set position to blinking position

		return self.simulator.get_pos()[0]

	def pupil_size(self):

		"""Dummy pupil size"""

		return 0

	def wait_for_event(self, event):

		"""Waits for simulated event (3=STARTBLINK, 4=ENDBLINK, 5=STARTSACC, 6=ENDSACC, 7=STARTFIX, 8=ENDFIX)"""

		if event == 5:
			self.wait_for_saccade_start()
		elif event == 6:
			self.wait_for_saccade_end()
		elif event == 7:
			self.wait_for_fixation_start()
		elif event == 8:
			self.wait_for_fixation_end()
		elif event == 3:
			self.wait_for_blink_start()
		elif event == 4:
			self.wait_for_blink_end()

		return (self.experiment.time(), ())

	def wait_for_saccade_start(self):

		"""Returns starting time and starting position when a simulated saccade is started"""

		# function assumes that a 'saccade' has been started when a deviation of more than
		# maxerr from the initial 'gaze' position has been detected (using Pythagoras, ofcourse)

		spos = self.sample() # starting position
		maxerr = 3 # pixels
		while True:
			npos = self.sample() # get newest sample
			if ((spos[0]-npos[0])**2  + (spos[1]-npos[1])**2)**0.5 > maxerr: # Pythagoras
				break

		return self.experiment.time(), spos

	def __wait_for_saccade_start_pre_10028(self):

		"""
		Returns starting time and starting position when a simulated saccade is started.
		(dummy for a libeyelink implementation that catches a pylink bug that existed before pylink 1.0.0.28)
		"""

		return self.wait_for_saccade_start()


	def wait_for_saccade_end(self):

		"""Returns ending time, starting and end position when a simulated saccade is ended"""

		# function assumes that a 'saccade' has ended when 'gaze' position remains reasonably
		# (i.e.: within maxerr) stable for five samples
		# for saccade start algorithm, see wait_for_fixation_start

		stime, spos = self.wait_for_saccade_start()
		maxerr = 3 # pixels
		
		# wait for reasonably stable position
		xl = [] # list for last five samples (x coordinate)
		yl = [] # list for last five samples (y coordinate)
		moving = True
		while moving:
			# check positions
			npos = self.sample()
			xl.append(npos[0]) # add newest sample
			yl.append(npos[1]) # add newest sample
			if len(xl) == 5:
				# check if deviation is small enough
				if max(xl)-min(xl) < maxerr and max(yl)-min(yl) < maxerr:
                                        print xl
                                        print yl
					moving = False
				# remove oldest sample
				xl.pop(0); yl.pop(0)
			# wait for a bit, to avoid immediately returning (runs go faster than mouse moves)
			self.experiment.sleep(10)

		return self.experiment.time(), spos, (xl[len(xl)-1],yl[len(yl)-1])

	def wait_for_fixation_start(self):

		"""Returns starting time and position when a simulated fixation is started"""

		# function assumes a 'fixation' has started when 'gaze' position remains reasonably
		# stable for five samples in a row (same as saccade end)

		maxerr = 3 # pixels
		
		# wait for reasonably stable position
		xl = [] # list for last five samples (x coordinate)
		yl = [] # list for last five samples (y coordinate)
		moving = True
		while moving:
			npos = self.sample()
			xl.append(npos[0]) # add newest sample
			yl.append(npos[1]) # add newest sample
			if len(xl) == 5:
				# check if deviation is small enough
				if max(xl)-min(xl) < maxerr and max(yl)-min(yl) < maxerr:
					moving = False
				# remove oldest sample
				xl.pop(0); yl.pop(0)
			# wait for a bit, to avoid immediately returning (runs go faster than mouse moves)
			self.experiment.sleep(10)

		return self.experiment.time(), (xl[len(xl)-1],yl[len(yl)-1])

	def wait_for_fixation_end(self):

		"""Returns starting time and position when a simulated fixation is started"""

		# function assumes that a 'fixation' has ended when a deviation of more than maxerr
		# from the initial 'fixation' position has been detected (using Pythagoras, ofcourse)

		stime, spos = self.wait_for_fixation_start()
		maxerr = 3 # pixels
		
		while True:
			npos = self.sample() # get newest sample
			if ((spos[0]-npos[0])**2  + (spos[1]-npos[1])**2)**0.5 > maxerr: # Pythagoras
				break

		return self.experiment.time(), spos

	def wait_for_blink_start(self):

		"""Returns starting time and position of a simulated blink (mousebuttondown)"""

		# blinks are simulated with mouseclicks: a right mouseclick simulates the closing
		# of the eyes, a mousebuttonup the opening.

		if self.blinkfun:
			while not self.blinking:
				pos = self.sample()

			return self.experiment.time(), pos

		else:
			print("libeyelink_dummy: blink functionality not available")
			return self.experiment.time(), (0,0)

	def wait_for_blink_end(self):

		"""Returns ending time and position of a simulated blink (mousebuttonup)"""
		
		# blinks are simulated with mouseclicks: a right mouseclick simulates the closing
		# of the eyes, a mousebuttonup the opening.

		if self.blinkfun:
			# wait for blink start
			while not self.blinking:
				spos = self.sample()
			# wait for blink end
			while self.blinking:
				epos = self.sample()

			return self.experiment.time(), epos

		else:
			print("libeyelink_dummy: blink functionality not available")
			return self.experiment.time(), (0,0)

	def prepare_backdrop(self, canvas):
		pass

	def set_backdrop(self, backdrop):
		pass

class eyelink_graphics(custom_display):

	"""
	A custom graphics environment to provide calibration functionality using
	OpenSesame, rather than PyLinks built-in system. Derived from the examples
	provided with PyLink
	"""

	fgcolor = 255, 255, 255, 255
	bgcolor = 0, 0, 0, 255

	def __init__(self, experiment, tracker):

		"""
		Constructor

		Arguments:
		experiment -- opensesame experiment
		tracker -- an eyelink instance
		"""

		pylink.EyeLinkCustomDisplay.__init__(self)

		self.experiment = experiment
		self.my_canvas = canvas(self.experiment)
		self.my_keyboard = keyboard(self.experiment, timeout=0)
		self.my_mouse = mouse(self.experiment)

		self.__target_beep__ = synth(self.experiment, length = 50)
		self.__target_beep__done__ = synth(self.experiment, freq = 880, length = 200)
		self.__target_beep__error__ = synth(self.experiment, freq = 220, length = 200)

		self.state = None

		self.imagebuffer = array.array('l')
		self.pal = None
		self.size = (0,0)
		self.tmp_file = os.path.join(tempfile.gettempdir(), '__eyelink__.jpg')

		self.set_tracker(tracker)
		self.last_mouse_state = -1
		self.experiment.eyelink_esc_pressed = False

	def set_tracker(self, tracker):

		"""
		Connect the tracker to the graphics environment

		Arguments:
		tracker -- an eyelink instance
		"""

		self.tracker = tracker
		self.tracker_version = tracker.getTrackerVersion()
		if(self.tracker_version >=3):
			self.tracker.sendCommand("enable_search_limits=YES")
			self.tracker.sendCommand("track_search_limits=YES")
			self.tracker.sendCommand("autothreshold_click=YES")
			self.tracker.sendCommand("autothreshold_repeat=YES")
			self.tracker.sendCommand("enable_camera_position_detect=YES")

	def setup_cal_display (self):

		"""Setup the calibration display, which contains some instructions"""

		yc = self.my_canvas.ycenter()
		ld = 40
		self.my_canvas.clear()
		self.my_canvas.text("OpenSesame eyelink plug-in", y = yc - 5 * ld)
		self.my_canvas.text("Enter: Enter camera set-up", y = yc - 3 * ld)
		self.my_canvas.text("C: Calibration", y = yc - 2 * ld)
		self.my_canvas.text("V: Validation", y = yc - 1 * ld)
		self.my_canvas.text("Q: Exit set-up", y = yc - 0 * ld)
		self.my_canvas.text("A: Automatically adjust threshold", y = yc + 1 * ld)
		self.my_canvas.text("Up/ Down: Adjust threshold", y = yc + 2 * ld)
		self.my_canvas.text("Left/ Right: Switch camera view", y = yc + 3 * ld)
		self.my_canvas.show()

	def exit_cal_display(self):

		"""Clear the display"""

		self.my_canvas.clear()
		self.my_canvas.show()

	def record_abort_hide(self):

		"""What does it do?"""

		pass

	def clear_cal_display(self):

		"""Clear the display"""

		self.my_canvas.clear()
		self.my_canvas.show()


	def erase_cal_target(self):

		"""Is done before drawing"""

		pass

	def draw_cal_target(self, x, y):

		"""
		Draw the calibration target

		Arguments:
		x -- the x-coordinate of the target
		y -- the y-coordinate of the target
		"""

		self.my_canvas.clear()

		self.my_canvas.circle(x, y, r=self.experiment.eyelink.cal_target_size, fill=True)
		self.my_canvas.circle(x, y, r=2, color=self.experiment.background, fill=True)
		self.my_canvas.show()
		if self.experiment.eyelink.cal_beep:
			self.play_beep(pylink.CAL_TARG_BEEP)

	def play_beep(self, beepid):

		"""
		Play a sound

		Arguments:
		beepid -- a pylink beep id
		"""

		if beepid == pylink.CAL_TARG_BEEP:
			self.__target_beep__.play()
		elif beepid == pylink.CAL_ERR_BEEP or beepid == pylink.DC_ERR_BEEP:
			self.my_canvas.clear()
			self.my_canvas.text("Calibration unsuccessfull", y = self.my_canvas.ycenter() - 20)
			self.my_canvas.text("Press 'Enter' to return to menu", y = self.my_canvas.ycenter() + 20)
			self.my_canvas.show()
			self.__target_beep__error__.play()
		elif beepid == pylink.CAL_GOOD_BEEP:
			self.my_canvas.clear()
			if self.state == "calibration":
				self.my_canvas.text("Success!", y = self.my_canvas.ycenter() - 20)
				self.my_canvas.text("Press 'v' to validate", y = self.my_canvas.ycenter() + 20)
			elif self.state == "validation":
				self.my_canvas.text("Success!", y = self.my_canvas.ycenter() - 20)
				self.my_canvas.text("Press 'Enter' to return to menu", y = self.my_canvas.ycenter() + 20)
			else:
				self.my_canvas.text("Press 'Enter' to return to menu")
			self.my_canvas.show()
			self.__target_beep__done__.play()
		else: #	DC_GOOD_BEEP	or DC_TARG_BEEP
			pass

	def getColorFromIndex(self,colorindex):

		"""Unused"""

		pass

	def draw_line(self, x1, y1, x2, y2, colorindex):

		"""Unused"""

		pass

	def draw_lozenge(self,x,y,width,height,colorindex):

		"""Unused"""

		pass

	def get_mouse_state(self):

		"""Unused"""

		pass

	def get_input_key(self):

		"""
		Get an input key

		Returns:
		A list of (keycode, moderator tuples)
		"""

		try:
			key, time = self.my_keyboard.get_key()
		except response_error:
			key = 'escape'
			self.experiment.eyelink_esc_pressed = True
		except:
			return None
		
		if key == "return":
			keycode = pylink.ENTER_KEY
			self.state = None
		elif key == "space":
			keycode = ord(" ")
		elif key in ["q", "escape"]:
			keycode = pylink.ESC_KEY
			self.state = None
		elif key == "c":
			keycode = ord("c")
			self.state = "calibration"
		elif key == "v":
			keycode = ord("v")
			self.state = "validation"
		elif key == "a":
			keycode = ord("a")
		elif key == "up":
			keycode = pylink.CURS_UP
		elif key == "down":
			keycode = pylink.CURS_DOWN
		elif key == "left":
			keycode = pylink.CURS_LEFT
		elif key == "right":
			keycode = pylink.CURS_RIGHT
		else:
			keycode = 0

		return [pylink.KeyInput(keycode, pygame.KMOD_NONE)]

	def exit_image_display(self):

		"""Exit the image display"""

		self.clear_cal_display()

	def alert_printf(self,msg):

		"""Print alert message"""

		print "eyelink_graphics.alert_printf(): %s" % msg

	def setup_image_display(self, width, height):

		"""
		Setup the image display

		Arguments:
		width -- the width of the display
		height -- the height of the display
		"""

		self.size = (width,height)
		self.clear_cal_display()
		self.last_mouse_state = -1
		self.imagebuffer = array.array('l')

	def image_title(self, text):

		"""Unused"""

		pass

	def draw_image_line(self, width, line, totlines, buff):

		"""
		Draws a single eye video frame

		Arguments:
		width -- the width of the video
		line -- the line nr of the current line
		totlines -- the total nr of lines in a video
		buff -- the frame buffer
		"""

		for i in range(width):
			try:
				self.imagebuffer.append(self.pal[buff[i]])
			except:
				pass

		if line == totlines:
			bufferv = self.imagebuffer.tostring()
			img = Image.new("RGBX", self.size)
			img.fromstring(bufferv)
			img = img.resize(self.size)
			img = pygame.image.fromstring(img.tostring(), self.size, "RGBX")
			self.my_canvas.clear()
			pygame.image.save(img, self.tmp_file)
			self.my_canvas.image(self.tmp_file, scale=2.)
			self.my_canvas.show()
			self.imagebuffer = array.array('l')

	def set_image_palette(self, r, g, b):

		"""Set the image palette"""

		self.imagebuffer = array.array('l')
		self.clear_cal_display()
		sz = len(r)
		i =0
		self.pal = []
		while i < sz:
			rf = int(b[i])
			gf = int(g[i])
			bf = int(r[i])
			self.pal.append((rf<<16) | (gf<<8) | (bf))
			i = i+1




