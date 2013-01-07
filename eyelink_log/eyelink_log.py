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

from libopensesame import item, exceptions
from libqtopensesame import qtplugin, inline_editor
import os.path
from PyQt4 import QtGui, QtCore

class eyelink_log(item.item):

	"""
	This class (the class with the same name as the module)
	handles the basic functionality of the item. It does
	not deal with GUI stuff.
	"""

	def __init__(self, name, experiment, string=None):

		"""
		Constructor
		"""

		# The item_typeshould match the name of the module
		self.item_type = "eyelink_log"
		self.msg = ""
		self.auto_log = 'no'

		# Provide a short accurate description of the items functionality
		self.description = \
			"Message log for the Eyelink series of eye trackers (SR-Research)"

		# The parent handles the rest of the contruction
		item.item.__init__(self, name, experiment, string)

	def prepare(self):

		"""
		Prepare the item. In this case this means drawing a fixation
		dot to an offline canvas.
		"""

		# Pass the word on to the parent
		item.item.prepare(self)

		# Create an eyelink instance if it doesn't exist yet. Libeyelink is
		# dynamically loaded
		if not hasattr(self.experiment, "eyelink"):
			raise exceptions.runtime_error( \
				"Please connect to the eyelink using the the eyelink_calibrate plugin before using any other eyelink plugins")

		self._msg = self.msg.split("\n")

		# Report success
		return True

	def run(self):

		"""
		Run the item. In this case this means putting the offline canvas
		to the display and waiting for the specified duration.
		"""

		self.set_item_onset()

		for msg in self._msg:
			self.experiment.eyelink.log(self.eval_text(msg))
			self.sleep(2)

		if self.auto_log == 'yes':
			for logvar, _val, item in self.experiment.var_list():
				val = self.get_check(logvar, default='NA')
				self.experiment.eyelink.log('var %s %s' % (logvar, val))

		# Report success
		return True

class qteyelink_log(eyelink_log, qtplugin.qtplugin):

	"""
	This class (the class named qt[name of module] handles
	the GUI part of the plugin. For more information about
	GUI programming using PyQt4, see:
	<http://www.riverbankcomputing.co.uk/static/Docs/PyQt4/html/classes.html>
	"""

	def __init__(self, name, experiment, string = None):

		"""
		Constructor
		"""

		# Pass the word on to the parents
		eyelink_log.__init__(self, name, experiment, string)
		qtplugin.qtplugin.__init__(self, __file__)

	def init_edit_widget(self):

		"""
		This function creates the controls for the edit
		widget.
		"""

		# Lock the widget until we're doing creating it
		self.lock = True

		# Pass the word on to the parent
		qtplugin.qtplugin.init_edit_widget(self, False)
		self.add_checkbox_control('auto_log', \
			'Auto-detect and log all variables', tooltip= \
			'Automatically auto-detect and log variables')
		self.add_editor_control("msg", "Log message", tooltip= \
			"The message to write to the Eyelink")

		# Unlock
		self.lock = True

	def apply_edit_changes(self):

		"""Apply the controls"""

		if not qtplugin.qtplugin.apply_edit_changes(self, False) or self.lock:
			return
		self.experiment.main_window.refresh(self.name)

	def edit_widget(self):

		"""Update the controls"""

		self.lock = True
		qtplugin.qtplugin.edit_widget(self)
		self.lock = False
		return self._edit_widget
